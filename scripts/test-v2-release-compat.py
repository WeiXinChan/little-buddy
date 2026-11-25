#!/usr/bin/env python3
import copy
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('pairing',Path(__file__).with_name('verify-v2-release.py'))
pairing=importlib.util.module_from_spec(spec);spec.loader.exec_module(pairing)

class Pairing(unittest.TestCase):
    def setUp(self):
        self.apk=dict(format=1,protocol_contract=pairing.CONTRACT,wire=2,images_v=1,management_v=1,
            local_help_v=1,session_end_v=1,resources_manifest_sha256='a'*64)
        self.backend=dict(format=1,source_sha='b'*40,protocol_contract=pairing.CONTRACT,assets_manifest_sha256='a'*64,
            files={'assets/v2-default/manifest.json':{'sha256':'a'*64}})
    def test_exact_pair(self):pairing.compatible(self.apk,self.backend)
    def test_unknown_backend_contract(self):
        self.backend['protocol_contract']='future'
        with self.assertRaises(ValueError):pairing.compatible(self.apk,self.backend)
    def test_unknown_apk_capability(self):
        self.apk['images_v']=2
        with self.assertRaises(ValueError):pairing.compatible(self.apk,self.backend)
    def test_different_resource_library(self):
        self.backend['files']['assets/v2-default/manifest.json']['sha256']='c'*64
        with self.assertRaises(ValueError):pairing.compatible(self.apk,self.backend)
    def test_missing_resource_and_bad_ref(self):
        for key,value in [('files',{}),('source_sha','/private/path'),('assets_manifest_sha256',None)]:
            candidate=copy.deepcopy(self.backend);candidate[key]=value
            with self.assertRaises(ValueError):pairing.compatible(self.apk,candidate)

if __name__=='__main__':unittest.main()
