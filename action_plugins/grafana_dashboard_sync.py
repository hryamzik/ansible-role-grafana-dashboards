#!/usr/bin/python
# -*- coding: utf-8 -*-

from ansible.plugins.action import ActionBase
from ansible.module_utils.basic import AnsibleModule
from ansible.errors import AnsibleError, AnsibleParserError
import os
from glob import glob
import re
import json
import tempfile
import uuid
# from datetime import datetime

class ActionModule(ActionBase):
    
    def getLocalDashboardList(self):
        path = self.path
        # all_json_files = [y for x in os.walk(path) for y in glob(os.path.join(x[0], '*.json'))]
        paths = []
        for x in os.walk(path):
            for y in glob(os.path.join(x[0], '*.json')):
                if not y.startswith(self.mapping_dir):
                    paths.append(re.sub('^' + path + '/?', '', y))
        return paths
        
    def readFile(self, file_path):
        if os.path.exists(file_path):
            try:
                with open(file_path) as json_data:
                    return json.load(json_data)
            except Exception as e:
                raise AnsibleError("Invalid dashboard JSON file at %s: %s" % (file_path, e.message))
        return None
    
    def uuidGen(self):
        return str(uuid.uuid4())
    
    def validateUUID(self, idstr):
        if idstr == None:
            return True, self.uuidGen()
        try:
            if idstr == str(uuid.UUID(idstr, version=4)):
                return False, idstr
        except Exception as e:
            pass
        return True, self.uuidGen()
    
    def getLocalDashboards(self):
        # slug can be imported only in a module #27748
        local_dashboards_titles = []
        local_dashboard_list = []
        local_dashboards = {}
        local_dashboards_uuids = {}
        
        for dash_path in self.local_dashboards_paths:
            dash = self.readFile("%s/%s" % (self.path,dash_path))
            if not dash or "id" not in dash or "title" not in dash:
                raise AnsibleError("Invalid dashboard %s" % dash_path)


            local_dashboards_titles.append(dash["title"])
            local_dashboard_list.append({"dashboard": dash, "path": dash_path})
        
        self.args["action"] = "slug"
        self.args["action_args"] = json.dumps(local_dashboards_titles)
        slug_result = self._execute_module(module_args=self.args, task_vars=self.task_vars)
        if "failed" in slug_result and slug_result["failed"]:
            raise AnsibleError("Slug failed: %s" % slug_result["msg"])
        # raise AnsibleError("slugged = %s" % slug_result["slugged"])
        for dash in local_dashboard_list:
            # raise AnsibleError("dash: %s" % slug_result["slugged"][dash["dashboard"]["title"]])
            dash["slug"] = slug_result["slugged"][dash["dashboard"]["title"]]
            if dash["slug"] in local_dashboards:
                raise AnsibleError("Duplicate dashboard %s, %s" % (local_dashboards[dash["slug"]]["path"], dash["path"]))
            if dash["dashboard"]["id"] in local_dashboards_uuids:
                raise AnsibleError("Duplicate dashboard ID (UUID: %s): '%s' and  '%s'" % (dash["dashboard"], local_dashboards_uuids[dash["dashboard"]], dash["path"]))
            updated_uuid, dash["dashboard"]["id"] = self.validateUUID(dash["dashboard"]["id"])
            if updated_uuid:
                local_dashboards_uuids[dash["dashboard"]["id"]] = dash["path"]
                self.uuided_dashboard_slugs.append(dash["slug"])
            local_dashboards[dash["slug"]] = dash
        self.local_dashboards = local_dashboards
        self.saveDashboardUUIDs()
    
    def saveDashboardUUIDs(self):
        for slug in self.uuided_dashboard_slugs:
            self.saveJson(self.local_dashboards[slug]['dashboard'], "%s/%s" % (self.path, self.local_dashboards[slug]["path"]))
            self.uuided_dashboards.append(self.local_dashboards[slug]["path"])
            self.changed = True
    
    def getRemoteDashboards(self):
        self.args["action"] = "get_dashboards"
        self.args["action_args"] = "{}"
        run_result = self._execute_module(module_args=self.args, task_vars=self.task_vars)
        if "failed" in run_result and run_result["failed"]:
            if run_result["msg"] == "MODULE FAILURE":
                raise AnsibleError("Getting remote dashboards failed: %s" % run_result)
            else:
                raise AnsibleError("Getting remote dashboards failed: %s" % run_result["msg"])
        self.remote_dashboards = run_result["dashboards"]
    
    def readMappings(self):
        mappings = self.readFile(self.mapping_file_path)
        if not mappings:
            mappings = {}
        self.mappings = mappings
    
    def saveMappings(self):
        if not self.check_mode:
            self.saveJson(self.mappings, self.mapping_file_path)
    
    def saveJson(self, content, file_path):
        if not self.check_mode:
            _, tmpfile = tempfile.mkstemp()
            with open(tmpfile, "w") as outfile:
                json.dump(content, outfile, sort_keys=True, indent=4, separators=(',', ': '))
            self.move_file(tmpfile, file_path)
        
    def move_file(self, src, dst):
        """should use atomic_move but didn't find a way to call it in action plugin"""
        if not self.check_mode:
            os.rename(src, dst)
    
    def _mappingInfoFromRemoteDashboard(self, dash):
        flatInfo = self.mappingInfoFromRemoteDashboard(dash)
        return self.mappingInfoUnflat(flatInfo)
    
    def mappingInfoFromRemoteDashboard(self, dash):
        info = {}
        for k in ["updated", "slug", "id", "version"]:
            info[k] = dash[k]
        return info
    
    def mappingInfoUnflat(self, m):
        info = {}
        for k in ["updated", "slug"]:
            info[k] = m[k]
        info["instances"] = {}
        info["instances"][self.instance_name] = {}
        for k in ["id", "version"]:
            info["instances"][self.instance_name][k] = m[k]
        return info

    def createMappingIfNotExist(self, dash_uuid, dashboard):
        info = self._mappingInfoFromRemoteDashboard(dashboard)
        if dash_uuid not in self.mappings:
            self.mappings[dash_uuid] = info
        elif self.instance_name not in self.mappings[dash_uuid]["instances"] or self.mappings[dash_uuid]["instances"][self.instance_name] != info["instances"][self.instance_name]:
            self.mappings[dash_uuid]["instances"][self.instance_name] = info["instances"][self.instance_name]
        else:
            return
        self.changed = True
        self.saveMappings()
    
    def updateMappingForRemoteDashboardIfRequired(self, slug, limit = 1):
        if limit < 0:
            raise AnsibleError("Recursion limit exceeded during updating mapping for %s" % slug)
        remote_info = self.mappingInfoFromRemoteDashboard(self.remote_dashboards[slug])
        local_uuid, local_info = self.getMappingForRemoteDahsboardID(self.remote_dashboards[slug]["id"])
        mapping_changed = False
        if remote_info != local_info:
            mapping_changed = True
            if local_uuid == None:
                _, local_uuid = self.validateUUID(self.remote_dashboards[slug]["dashboard"]["id"])
                self.createMappingIfNotExist(local_uuid, self.remote_dashboards[slug])
                return self.updateMappingForRemoteDashboardIfRequired(slug, limit -1)

            if remote_info["version"] < local_info["version"]:
                raise AnsibleError("Error saving dashboard %s, version downgrade detected" % slug)
            elif remote_info["id"] != local_info["id"]:
                raise AnsibleError("Error saving dashboard %s, id mismatch" % slug)
            elif remote_info["version"] > local_info["version"]:
                for i in self.mappings[local_uuid]["instances"]:
                    self.mappings[local_uuid]["instances"][i]["version"] += 1

            self.mappings[local_uuid]["instances"][self.instance_name] = self.mappingInfoUnflat(remote_info)["instances"][self.instance_name]
            self.mappings[local_uuid]["updated"] = remote_info["updated"]
            self.mappings[local_uuid]["slug"] = remote_info["slug"]
            if local_uuid == None:
                raise AnsibleError("uuid not found for %s" % slug)

        if mapping_changed:
            self.saveMappings()
            self.changed = True            
    
    def mapPostResults(self, post_results):
        """
        {"mydashboard": {"updated": "2017-08-10T08:08:25Z", "version": 23, "id": 7, "slug": "mydashboard"}
        """
        mapping_changed = False
        for slug in post_results:
            remote_info = self.mappingInfoFromRemoteDashboard(post_results[slug])
            local_uuid, local_info = self.getMappingForRemoteDahsboardID(post_results[slug]["id"])
            if remote_info != local_info:
                mapping_changed = True
                if not local_uuid:
                    local_uuid = self.local_dashboards[slug]["dashboard"]["id"]
                    self.mappings[local_uuid] = self.mappingInfoUnflat(remote_info)
                else:
                    self.mappings[local_uuid]["instances"][self.instance_name] = self.mappingInfoUnflat(remote_info)["instances"][self.instance_name]

        if mapping_changed:
            self.saveMappings()
            self.changed = True
    
    def flatMapping(self, m):
        mapping = {}
        for k in ["updated", "slug"]:
            mapping[k] = m[k]
        for k in ["id", "version"]:
            mapping[k] = m["instances"][self.instance_name][k]
        return mapping
    
    def getMappingForLocalDahsboardID(self, dash_id):
        if dash_id not in self.mappings:
            return None
        m = self.mappings[dash_id]
        if self.instance_name not in m["instances"]:
            return None
        return self.flatMapping(m)
    
    def getMappingForRemoteDahsboardID(self, dash_id):
        for u in self.mappings:
            if self.instance_name in self.mappings[u]["instances"]:
                if self.mappings[u]["instances"][self.instance_name]["id"] == dash_id:
                    return u, self.flatMapping(self.mappings[u])
        return None, None
    
    def removeDashboardFromMapping(self,dash_uuid):
        mapping_changed = False
        if dash_uuid in self.mappings:
            if self.instance_name in self.mappings[dash_uuid]["instances"]:
                self.mappings[dash_uuid]["instances"].pop(self.instance_name, '')
                mapping_changed = True
            if len(self.mappings[dash_uuid]["instances"]) == 0:
                self.mappings.pop(dash_uuid, '')
                mapping_changed = True
        if mapping_changed:
            self.saveMappings()
            self.changed = True    
    
    def compareDashboards(self):
        dashboard_slugs_to_upload = []
        dashboard_slugs_to_download = []
        mapped_dashboard_slugs = {}
        local_unmapped_dashboard_slugs = []
        remote_unmapped_dashboard_slugs = []
        local_dashboard_slugs_to_delete = []
        remote_dashboard_slugs_to_delete = []
        
        for lslug in self.local_dashboards:
            local_uuid = self.local_dashboards[lslug]["dashboard"]["id"]
            mapping = self.getMappingForLocalDahsboardID(local_uuid)
            if mapping:
                if local_uuid not in mapped_dashboard_slugs:
                    mapped_dashboard_slugs[local_uuid] = {}
                mapped_dashboard_slugs[local_uuid]["local"] = lslug
            else:
                local_unmapped_dashboard_slugs.append(lslug)
        for rslug in self.remote_dashboards:
            local_uuid, mapping = self.getMappingForRemoteDahsboardID(self.remote_dashboards[rslug]["dashboard"]["id"])
            if mapping:
                if local_uuid not in mapped_dashboard_slugs:
                    mapped_dashboard_slugs[local_uuid] = {}
                mapped_dashboard_slugs[local_uuid]["remote"] = rslug
            else:
                remote_unmapped_dashboard_slugs.append(rslug)
        
        # raise AnsibleError("compareDashboards: local_unmapped_dashboard_slugs = %s" % local_unmapped_dashboard_slugs)
        dashboard_slugs_to_upload = list(set(local_unmapped_dashboard_slugs) - set(remote_unmapped_dashboard_slugs))        
        dashboard_slugs_to_download = list(set(remote_unmapped_dashboard_slugs) - set(local_unmapped_dashboard_slugs))
        interception = set(remote_unmapped_dashboard_slugs).intersection(local_unmapped_dashboard_slugs)
        
        for slug in dashboard_slugs_to_download:
            _, self.remote_dashboards[slug]["dashboard"]["id"] = self.validateUUID(self.remote_dashboards[slug]["dashboard"]["id"])
        
        for slug in interception:
            self.remote_dashboards[slug]['dashboard']["id"] = self.local_dashboards[slug]['dashboard']["id"]
            # raise AnsibleError("compareDashboards: local, remote ids = %s, %s, %s" % (self.local_dashboards[slug]['dashboard']["id"], self.remote_dashboards[slug]['dashboard']["id"], self.remote_dashboards[slug]["id"]))
            if self.local_dashboards[slug]['dashboard']['version'] < self.remote_dashboards[slug]['dashboard']['version']:
                dashboard_slugs_to_download.append(slug)
            elif self.local_dashboards[slug]['dashboard']['version'] > self.remote_dashboards[slug]['dashboard']['version']:
                dashboard_slugs_to_upload.append(slug)
            else:
                dash_uuid = self.local_dashboards[slug]['dashboard']["id"]
                self.createMappingIfNotExist(dash_uuid, self.remote_dashboards[slug])
                # raise AnsibleError("compareDashboards: versions match, mapping has to be created")
                
        for local_uuid in mapped_dashboard_slugs:
            if "local" not in mapped_dashboard_slugs[local_uuid] and "remote" not in mapped_dashboard_slugs[local_uuid]:
                raise AnsibleError("Invalid mapped_dashboard_slugs dictionary: %s" % mapped_dashboard_slugs)
            elif "local" not in mapped_dashboard_slugs[local_uuid]:
                remote_dashboard_slugs_to_delete.append(mapped_dashboard_slugs[local_uuid]["remote"])
            elif "remote" not in mapped_dashboard_slugs[local_uuid]:
                local_dashboard_slugs_to_delete.append(mapped_dashboard_slugs[local_uuid]["local"])
            else:
                rdash = self.remote_dashboards[mapped_dashboard_slugs[local_uuid]["remote"]]
                lmapping = self.getMappingForLocalDahsboardID(local_uuid)
                # lval, rval = datetime.strptime(lmapping["updated"], '%Y-%m-%dT%H:%M:%SZ'), datetime.strptime(rdash["updated"], '%Y-%m-%dT%H:%M:%SZ')
                lval, rval = lmapping["version"], rdash["version"]
                if lval > rval:
                    dashboard_slugs_to_upload.append(mapped_dashboard_slugs[local_uuid]["local"])
                elif lval < rval:
                    dashboard_slugs_to_download.append(mapped_dashboard_slugs[local_uuid]["remote"])
            # raise AnsibleError("compareDashboards: versions match, mapping has to be created")
            # raise AnsibleError("upload: %s, download: %s" % (dashboard_slugs_to_upload, dashboard_slugs_to_download))
            # raise AnsibleError("upload: %s, download: %s" % (self.local_dashboards[dashboard_slugs_to_upload[0]], dashboard_slugs_to_download))

        self.dashboard_slugs_to_upload        = dashboard_slugs_to_upload
        self.dashboard_slugs_to_download      = dashboard_slugs_to_download
        self.local_dashboard_slugs_to_delete  = local_dashboard_slugs_to_delete
        self.remote_dashboard_slugs_to_delete = remote_dashboard_slugs_to_delete
        # raise AnsibleError("Delete list: %s" % self.local_dashboard_slugs_to_delete)        
    
    def fixLocalDahsboardsNames(self):
        for slug in self.local_dashboards:
            if self.local_dashboards[slug]["path"] != slug + '.json':
                src, dst = self.local_dashboards[slug]["path"], "%s.json" % slug
                self.setLocaldashboardName(src, dst)
                self.local_dashboards[slug]["path"] = slug + '.json'
    
    def setLocaldashboardName(self, src, dst):
        self.move_file("%s/%s" % (self.path, src), "%s/%s" % (self.path, dst))
        self.moved_files.append({ "src": src, "dst": dst })
        self.changed = True    
    
    def localDashboardSlugByUUID(self, dash_uuid):
        for dash in self.local_dashboards:
            if self.local_dashboards[dash]["dashboard"]["id"] == dash_uuid:
                return dash
        return None    
    
    def saveRemoteDashboards(self):
        for slug in self.dashboard_slugs_to_download:
            self.updateMappingForRemoteDashboardIfRequired(slug)
            dst = "%s.json" % slug
            local_uuid, mapping = self.getMappingForRemoteDahsboardID(self.remote_dashboards[slug]['id'])
            if local_uuid == None:
                raise AnsibleError("No UUID for %s" % self.remote_dashboards[slug]["dashboard"]["id"])
            lslug = self.localDashboardSlugByUUID(local_uuid)
            if lslug != None:
                ldash_path = self.local_dashboards[lslug]["path"]
                src = ldash_path
                if src != dst:
                    self.setLocaldashboardName(src, dst)
                    self.local_dashboards[lslug]["path"] = dst
            self.remote_dashboards[slug]["dashboard"]["id"] = local_uuid
            self.saveJson(self.remote_dashboards[slug]['dashboard'], "%s/%s" % (self.path, dst))
            self.downloaded_dashboards.append(dst)
            self.changed = True
    
    def removeLocalDashboards(self):
        for lslug in self.local_dashboard_slugs_to_delete:
            self.changed = True
            ldash = self.local_dashboards[lslug]
            path = ldash["path"]
            if not self.check_mode:
                os.remove("%s/%s" % (self.path, path))
            dash_uuid = self.local_dashboards[lslug]["dashboard"]["id"]
            self.removeDashboardFromMapping(dash_uuid)
    
    def removeRemoteDashboards(self):
        if not self.check_mode:
            self.args["action"] = "delete_dashboards"
            self.args["action_args"] = json.dumps(self.remote_dashboard_slugs_to_delete)
            run_result = self._execute_module(module_args=self.args, task_vars=self.task_vars)
            if "failed" in run_result and run_result["failed"]:
                if run_result["msg"] == "MODULE FAILURE":
                    raise AnsibleError("Deleting remote dashboards failed: %s" % run_result)
                else:
                    raise AnsibleError("Deleting remote dashboards failed: %s" % run_result["msg"])
            # raise AnsibleError("Delete result: %s" % run_result)
        for rslug in self.remote_dashboard_slugs_to_delete:
            dash_uuid, _ = self.getMappingForRemoteDahsboardID(self.remote_dashboards[rslug]["id"])
            self.removeDashboardFromMapping(dash_uuid)
    
    def uploadDashboards(self):
        dashboards_upload = {}
        for slug in self.dashboard_slugs_to_upload:
            self.changed = True
            self.uploaded_dashboards.append(slug)
            dashboards_upload[slug] = self.local_dashboards[slug]
            mapping = self.getMappingForLocalDahsboardID(self.local_dashboards[slug]["dashboard"]["id"])
            if mapping:
                dashboards_upload[slug]["dashboard"]["version"] = mapping["version"]
                dashboards_upload[slug]["dashboard"]["id"] = mapping["id"]
                
        if not self.check_mode:
            self.args["action"] = "upload_dashboards"
            self.args["action_args"] = json.dumps(dashboards_upload)
            run_result = self._execute_module(module_args=self.args, task_vars=self.task_vars)
            if "failed" in run_result and run_result["failed"]:
                if run_result["msg"] == "MODULE FAILURE":
                    raise AnsibleError("Posting dashboards failed: %s" % run_result)
                else:
                    raise AnsibleError("Posting dashboards failed: %s" % run_result["msg"])
            post_results = run_result["post_results"]
            self.mapPostResults(post_results)
    
    def run(self, tmp=None, task_vars=None):
        self.changed = False
        self.moved_files = []
        self.downloaded_dashboards = []
        self.uploaded_dashboards = []
        self.uuided_dashboards = []
        self.local_dashboard_slugs_to_delete = []
        self.remote_dashboard_slugs_to_delete = []
        
        self.uuided_dashboard_slugs = []
        
        if task_vars is None:
            task_vars = dict()
        self.task_vars = task_vars
        args = self._task.args.copy()
        self.args = args
        path = re.sub('/*$', '', args['path'])
        self.path = path
        if "mapping_dir" not in args:
            args["mapping_dir"] = "%s/mappings" % path
        self.mapping_dir = re.sub('/*$', '', args["mapping_dir"])
        
        self.check_mode = task_vars["ansible_check_mode"]
        result = super(ActionModule, self).run(tmp, task_vars)
        # self._execute_module(module_args=args, task_vars=task_vars)
        
        
        self.local_dashboards_paths = self.getLocalDashboardList()
        
        self.mapping_file_path = "%s/mappings.json" % (self.mapping_dir)
        self.instance_name = args["name"]
        
        self.readMappings()
        
        self.getLocalDashboards()
        
        self.getRemoteDashboards()

        self.compareDashboards()

        self.fixLocalDahsboardsNames()

        self.saveRemoteDashboards()
        
        self.removeLocalDashboards()

        self.uploadDashboards()
        
        self.removeRemoteDashboards()

        # result.update(self._execute_module(module_args=args, task_vars=task_vars))
        
        result["moved_files"] = self.moved_files
        result["downloaded_dashboards"] = self.downloaded_dashboards
        result["uploaded_dashboards"] = self.uploaded_dashboards
        result["uuided_dashboards"] = self.uuided_dashboards
        result["local_deleted_dashboard"] = self.local_dashboard_slugs_to_delete
        result["remote_deleted_dashboards"] = self.remote_dashboard_slugs_to_delete
        result["changed"] = self.changed
        
        return result
