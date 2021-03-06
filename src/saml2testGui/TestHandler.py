# -*- coding: utf-8 -*-
import cgi
import copy

import json
import subprocess
from saml2.httputil import Response, ServiceError

import glob
from os.path import basename
import os
import uuid
from urllib import quote
__author__ = 'haho0032'

class Test:
    IDP_TESTDRV = '/usr/local/bin/idp_testdrv.py'

    #Only used to check to check for new config files this which does nothing useful for the moment
    CONFIG_FILE_PATH = 'saml2test/configFiles/'

    def __init__(self, environ, start_response, session, logger, lookup, config, parameters, cache):
        """
        Constructor for the class.
        :param environ:        WSGI enviroment
        :param start_response: WSGI start_respose
        :param session:        Beaker session
        :param logger:         Class to perform logging.
        """
        self.environ = environ
        self.start_response = start_response
        self.session = session
        self.logger = logger
        self.lookup = lookup
        self.config = config
        self.parameters = parameters
        self.urls = {
            "" : "index.mako",
            "list" : None,
            "config" : None,
            "run_test" : None
        }
        self.cache = cache



    def verify(self, path):
        for url, file in self.urls.iteritems():
            if path == url:
                return True


    def handle(self, path):
        if path == "":
            return self.handleIndex(self.urls[path])
        elif path == "list":
            return self.handleList()
        elif path == "config":
            return self.handleConfigFiles()
        elif path == "run_test":
            return self.handleRunTest()


    def handleIndex(self, file):
        resp = Response(mako_template=file,
                        template_lookup=self.lookup,
                        headers=[])
        argv = {
            "a_value": "Hello world"
        }
        return resp(self.environ, self.start_response, **argv)


    def handleList(self):
        #Gör en knapp som ändrar synen på trädet
        #showBottomUp = self.parameters['treeType']
        if "handleList_result" not in self.cache:

            if "test_list" not in self.cache:
                ok, p_out, p_err = self.runScript([self.IDP_TESTDRV, '-l'])
                if ok:
                    self.cache["test_list"] = p_out
            else:
                ok = True
            #ok, p_out, p_err = self.runScript([self.IDP_TESTDRV, '-l'])
            allTests = json.loads(self.cache["test_list"])

            childTestsList, rootTestsList = self.identifyRootTests(allTests)

            topDownChildList = copy.deepcopy(childTestsList)
            topDownRootList = copy.deepcopy(rootTestsList)

            topDownTree = self.insertRemaningChildTestsTopdown(topDownChildList, topDownRootList)
            bottomUpTree = self.insertRemaningChildTestsBottomUp(childTestsList, rootTestsList)

            self.setupTestId(topDownTree)
            self.setupTestId(bottomUpTree)

            flatBottomUpTree = self.convertToFlatBottomTree(bottomUpTree)

            result = {
                "topDownTree": topDownTree,
                "bottomUpTree": bottomUpTree,
                "flatBottomUpTree": flatBottomUpTree
            }

            self.cache["handleList_result"] = result
        else:
            result = self.cache["handleList_result"]
            ok = True
        #currentFlattenedTree = [{'id': 'verify', 'level': '1', 'children': [{'id': 'authn', 'level': '2', 'children': [{'id': 'authn-post', 'level': '3', 'children': [{'id': 'authn-post-transient', 'level': '4', 'children': []}]}]}]}, {'id': 'ecp_authn', 'level': '1' , 'children': []}]

        if (ok):
            myJson = json.dumps(result) #json.dumps([{"id": "Node", "children": [{"id": "Node2","children": [{"id": "Node4","children": []}]}, {"id": "Node3","children": []}]}])
        else:
            return self.serviceError("Cannot list the tests.")
        return self.returnJSON(myJson)

    def handleConfigFiles(self):
        self.checkForNewConfigFiles()
        configJSONString = json.dumps(self.config.IDPTESTENVIROMENT)
        return self.returnJSON(configJSONString)


    def handleRunTest(self):
        testToRun = self.parameters['testname']
        targetFile = self.parameters['targetFile']

        if 'testid' in self.parameters:
            testid = self.parameters['testid']
        else:
            testid = None

        targetFile = targetFile.strip(' \n\t')

        if self.checkIfParamentersAreValid(targetFile, testToRun):
            #Directs to the folder containing the saml2test config file an enters the target.json files as a parameter to the test script
            ok, p_out, p_err = self.runScript([self.IDP_TESTDRV,'-J', 'configFiles/'+ targetFile + '.json', testToRun], "./saml2test")

            #self.formatOutput(p_out)

            if (ok):
                response = {
                    "result": json.loads(p_out),
                    "errorlog": cgi.escape(p_err),
                    "testid": testid
                }
                return self.returnJSON(json.dumps(response))
            else:
                return self.serviceError("Cannot run test")

        return self.serviceError("The test is not valid")

    #def formatOutput(self, p_out):
        #print (p_out[0])
        #returnValue = ""
        #for test in p_out:
           #print test.status



    def createNewTestDict(self, item, level=1):
        newDict = {}
        newDict['id'] = str(item["id"])
        newDict['children'] = []
        newDict['level'] = level
        newDict['testid'] = ""
        newDict['descr'] = str(item["name"]) #"name" ska bytas up mot "descr" men alla test innehåller inte dessa attribut
        return newDict


    def identifyRootTests(self, allTests):
        childTestsList = []
        rootTestsList = []
        for item in allTests:
            if not ('depend' in item):
                newDict = self.createNewTestDict(item)
                rootTestsList.append(newDict)
            else:
                childTestsList.append(item)
        return childTestsList, rootTestsList


    def setupTestId(self, tree, visible=True):
        for element in tree:
            element["visible"] = visible
            element["testid"] = uuid.uuid4().urn
            if element["children"] is not None and len(element["children"])>0:
                self.setupTestId(element["children"], False)


    def insertRemaningChildTestsBottomUp(self, childTestsList, leafTestList):
        tree = []

        while len(leafTestList) > 0:
            newleafTestsList = []
            leafsToRemove = []

            for leaf in leafTestList:
                for child in childTestsList:
                    parentList = child['depend']

                    for parent in parentList:
                        parent = str(parent)

                        if leaf['id'] == parent:
                            newChild = self.createNewTestDict(child)
                            newChild["children"].append(copy.deepcopy(leaf))
                            newChild["hasChildren"] = True
                            #Gå igenom alla barn och uppdatera deras level med 1
                            self.updateChildrensLevel(newChild);

                            newleafTestsList.append(newChild)
                            leafsToRemove.append(leaf)

            for leaf in leafTestList:
                if not (leaf in leafsToRemove):
                    tree.append(leaf)

            leafTestList = newleafTestsList

        return tree


    def updateChildrensLevel(self, child):
        childrenList = child['children']
        for unvisitedChild in childrenList:
            unvisitedChild['level'] = child['level'] + 1
            self.updateChildrensLevel(unvisitedChild)

    def convertToFlatBottomTree(self, bottomUpTree):
        flatBottomUpTree = []
        for rootTest in bottomUpTree:
            newTest = copy.deepcopy(rootTest)
            children = self.getChildren(newTest)
            newTest['children'] = children
            flatBottomUpTree.append(newTest)
        return flatBottomUpTree

    def getChildren(self, child):
        childrenToVisitList = child['children']
        allChildren = []

        while len(childrenToVisitList) > 0:
            newChildrenToVisitList = []
            for childToVisit in childrenToVisitList:
                grandchildren = childToVisit['children']
                for grandChild in grandchildren:
                    newChildrenToVisitList.append(grandChild)
                childToVisit['children'] = []
                childToVisit['hasChildren'] = False
                childToVisit['level'] = 2
                allChildren.insert(0, childToVisit)

            childrenToVisitList = newChildrenToVisitList
        return allChildren




    def updateChildrensLevelFlat(self, child):
        childrenList = child['children']
        for unvisitedChild in childrenList:
            if (child['level'] + 1) > 2:
                unvisitedChild['level'] = 2;
            else:
                unvisitedChild['level'] = child['level'] + 1
            self.updateChildrensLevel(unvisitedChild)


    def insertRemaningChildTestsTopdown(self, childTestsList, parentList):
        tree = parentList #Tree will be correct since it working on pointers.

        while len(childTestsList) > 0:
            newParentTestsList = []
            newChildTestsList = []

            for parent in parentList:
                for child in childTestsList:
                    parentID = child['depend']

                    if len(parentID) == 1:
                        parentID = str(parentID[0])
                    else:
                        pass
                        #Kasta ett fel.

                    if parent['id'] == parentID:
                        childLevel = parent["level"] + 1
                        newChild = self.createNewTestDict(child, childLevel)
                        parent["children"].append(newChild)
                        parent["hasChildren"] = True
                        newParentTestsList.append(newChild)

            for child in childTestsList:
                for newParent in newParentTestsList:
                    if not (child['id'] == newParent['id']):
                        if not (child in newChildTestsList):
                            newChildTestsList.append(child)


            childTestsList = newChildTestsList
            parentList = newParentTestsList
        return tree

    def getListedIdpEnviroments(self):
        listedIdpEnviroments = []
        for dictionary in self.config.IDPTESTENVIROMENT:
            listedIdpEnviroments.append(dictionary["Name"])
        return listedIdpEnviroments

    def checkForNewConfigFiles(self):
        listedIdpEnviroments = self.getListedIdpEnviroments()

        configPaths = glob.glob(self.CONFIG_FILE_PATH + "*.json")

        for path in configPaths:
            filename = basename(path)
            filenameNoExtention = os.path.splitext(filename)[0]

            """
            if (filenameNoExtention in listedIdpEnviroments):
                print filenameNoExtention
            else:
                print filenameNoExtention + " not specified in server_conf"
            """


    def checkIfParamentersAreValid(self, targetFile, testToRun):
        listedIdpEnviroments = self.getListedIdpEnviroments();

        if targetFile in listedIdpEnviroments:
            if self.checkIfIncommingTestIsLeagal(testToRun):
                return True


    def checkIfIncommingTestIsLeagal(self, tmpTest):
        testToRun = None
        if "verify_test_dict" not in self.cache:
            self.cache["verify_test_dict"] = {}
            if "test_list" not in self.cache:
                ok, p_out, p_err = self.runScript([self.IDP_TESTDRV, '-l'])
                if ok:
                    self.cache["test_list"] = p_out
            tests = json.loads(self.cache["test_list"])
            for test in tests:
                self.cache["verify_test_dict"][test["id"]] = True
                #if test["id"] == tmpTest:
                #    testToRun = test["id"]
        if tmpTest in self.cache["verify_test_dict"] and self.cache["verify_test_dict"][tmpTest] is True:
            return True
        else:
            return False


    def returnJSON(self, text):
        resp = Response(text, headers=[('Content-Type', "application/json")])
        return resp(self.environ, self.start_response)


    def serviceError(self, message):
        message = {"ExceptionMessage": message}
        resp = ServiceError(json.dumps(message))
        return resp(self.environ, self.start_response)


    def runScript(self, command, working_directory=None):
        try:
            p = subprocess.Popen(command,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 cwd=working_directory)
            while(True):
                retcode = p.poll() #returns None while subprocess is running
                if(retcode is not None):
                    break
            p_out = p.stdout.read()
            p_err = p.stderr.read()
            return (True, p_out, p_err)
        except Exception as ex:
            self.logger.fatal("Can not run command: +" + ex.message)
            return (False, None, None)