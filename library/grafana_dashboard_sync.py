#!/usr/bin/python
# -*- coding: utf-8 -*-
# Tests based on https://github.com/gosimple/slug/
# Code from:
#   - https://github.com/un33k/python-slugify
#   - https://github.com/iki/unidecode

from __future__ import absolute_import, division, print_function
__metaclass__ = type

import base64
import re
import shutil
import json

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.slugify import slugify
from ansible.module_utils.urls import fetch_url, url_argument_spec

def slug_test_pass():
    cases = [
        ["DOBROSLAWZYBORT",           "dobroslawzybort"],
        ["Dobroslaw Zybort",          "dobroslaw-zybort"],
        ["  Dobroslaw     Zybort  ?", "dobroslaw-zybort"],
        ["Dobrosław Żybort",          "dobroslaw-zybort"],
        ["Ala ma 6 kotów.",           "ala-ma-6-kotow"],
        ["áÁàÀãÃâÂäÄąĄą̊Ą̊",            "aaaaaaaaaaaaaa"],
        ["ćĆĉĈçÇ",                    "cccccc"],
        ["éÉèÈẽẼêÊëËęĘ",              "eeeeeeeeeeee"],
        ["íÍìÌĩĨîÎïÏįĮ",              "iiiiiiiiiiii"],
        ["łŁ",                        "ll"],
        ["ńŃ",                        "nn"],
        ["óÓòÒõÕôÔöÖǫǪǭǬø",           "ooooooooooooooo"],
        ["śŚ",                        "ss"],
        ["úÚùÙũŨûÛüÜųŲ",              "uuuuuuuuuuuu"],
        ["y̨Y̨",                        "yy"],
        ["źŹżŹ",                      "zzzz"],
        ["·/,:;`˜'\"",                ""],
        ["2000–2013",                 "2000-2013"],
        ["style—not",                 "style-not"],
        ["test_slug",                 "test_slug"],
        ["Æ",                         "ae"],
        ["Ich heiße",                 "ich-heisse"],
        ["This & that",               "this-and-that"],
        ["fácil €",                   "facil-eu"],
        ["smile ☺",                   "smile"],
        ["Hellö Wörld хелло ворлд",   "hello-world-khello-vorld"],
        ["\"C'est déjà l’été.\"",     "cest-deja-lete"],
        ["jaja---lol-méméméoo--a",    "jaja-lol-mememeoo-a"],
        ["影師",                      "ying-shi"],
    ]
    for case in cases:
        try:
            # slugged = slugify(case[0].decode('utf-8'))
            slugged = slugify(case[0])
            # return False, slugged
        except Exception as e:
            return False, e.message
        if slugged != case[1]:
            # raise AnsibleError("Slug test failed for '%s', expected '%s', got '%s'" % (case[0], case[1], slugged))
            return False, "Slug test failed for '%s', expected '%s', got '%s'" % (case[0], case[1], slugged)
    return True, ""

class Grafana:
    def __init__(self, module, baseurl, username, password):
        self.baseurl = baseurl
        self.module=module
        self.socket_timeout = 30
        self.headers = {
            'content-type': "application/json;charset=UTF-8",
            'authorization': "Basic %s" % base64.encodestring('%s:%s' % (username, password)).replace('\n', '')
            }
    def getDashboardList(self, search_query):
        if not search_query:
            search_query = ""
        # self.module.fail_json(msg="%s/api/search?query=%s, headers=%s" % (self.baseurl, search_query, self.headers))
        return self._uri("api/search?query=%s" % search_query, None, "GET")
    pass
    
    def _uri(self, url, body, method):
        content, status = self._uriWithStatus(url, body, method)
        return content
    
    def _uriWithStatus(self, url, body, method):
        # is dest is set and is a directory, let's check if we get redirected and
        # set the filename from that url
        redirected = False
        redir_info = {}
        r = {}
        if body:
            body=json.dumps(body)

        resp, info = fetch_url(self.module, "%s/%s" % (re.sub('/$','',self.baseurl), re.sub('^/','',url)), data=body, headers=self.headers,
                               method=method, timeout=self.socket_timeout)

        try:
            content = resp.read()
        except AttributeError:
            # there was no content, but the error read()
            # may have been stored in the info as 'body'
            content = info.pop('body', '')

        r['redirected'] = redirected or info['url'] != url
        r.update(redir_info)
        r.update(info)

        # return r, content, dest
        return json.loads(content), info
        # return content
        
    def getDashboardByUri(self, uri):
        grafana_dashboard = self._uri("api/dashboards/%s" % uri, None, "GET")
        grafana_dashboard["meta"]["id"] = grafana_dashboard["dashboard"]["id"]
        dashboard_result = {}
        for k in ["updated", "id", "version", "slug"]:
            dashboard_result[k] = grafana_dashboard["meta"][k]
        dashboard_result["dashboard"] = grafana_dashboard["dashboard"]
        return dashboard_result
    pass
    
    def postDashboard(self, dashboard):
        # self.module.fail_json(msg="dashboard slug=%s, keys=%s" % (dashboard["slug"], dashboard.keys()))
        post_result = self._uri("api/dashboards/db", { "overwrite": True, "dashboard": dashboard["dashboard"] } , "POST")
        if "status" not in post_result:
            self.module.fail_json(msg="Dashboard upload failed with unexpected responce: %s" % post_result)
        elif post_result["status"] != "success":
            self.module.fail_json(msg="Dashboard upload failed: %s, %s" % (post_result["status"], post_result["message"]))
        elif "slug" not in post_result:
            self.module.fail_json(msg="Dashboard upload failed: unexpected responce, 'slug' not found: %s" % post_result)
        elif post_result["slug"] != dashboard["slug"]:
            self.module.fail_json(msg="Dashboard upload error: slugs do not match, expected '%s', got '%s'" % (dashboard["slug"], post_result["slug"]))
        dashboard = self.getDashboardByUri("db/%s" % post_result["slug"])
        dashboard.pop("dashboard", None)
        return dashboard
    pass
    
    def deleteDashboard(self, slug):
        res, info = self._uriWithStatus("api/dashboards/db/%s" % slug, None , "DELETE")
        if info["status"] != 200:
            self.module.fail_json(msg=info)
        return res
    pass
    

def main():
    module = AnsibleModule(
        argument_spec = dict(
            url     = dict(default='http://127.0.0.1:3000'),
            path = dict(required=True),
            name = dict(required=True),
            username = dict(type='str'),
            password = dict(type='str', no_log=True),
            search_query = dict(required=False),
            mapping_dir = dict(),
            run_tests = dict(default=False, choices=[True, False], type='bool'),
            action = dict(required=False, type='str'),
            action_args = dict(required=False),
        ),
        supports_check_mode=True
    )
    
    action = module.params['action']
    action_args = json.loads(module.params['action_args'])
    run_tests = module.params['run_tests']
    local_path = module.params['path']
    search_query = module.params['search_query']
    if action:
        if action == "slug":
            slugged = {}
            for name in action_args:
                slugged[name] = slugify(name)
            module.exit_json(changed=False, slugged=slugged)
        elif action == "get_dashboards":
            grafana = Grafana(module, module.params['url'],module.params['username'], module.params['password'])
            dashboard_list = grafana.getDashboardList(search_query)
            dashboards = {}
            for dash in dashboard_list:
                if dash["type"] == "dash-db":
                    dashboard = grafana.getDashboardByUri(dash["uri"])
                    dashboards[dashboard["slug"]] = dashboard
            module.exit_json(changed=False, dashboards=dashboards)
        elif action == "upload_dashboards":
            grafana = Grafana(module, module.params['url'],module.params['username'], module.params['password'])
            post_results = {}
            dashboards_dict = action_args
            for slug in dashboards_dict:
                post_results[slug] = grafana.postDashboard(dashboards_dict[slug])
            module.exit_json(changed=True, post_results=post_results)
        elif action == "delete_dashboards":
            grafana = Grafana(module, module.params['url'],module.params['username'], module.params['password'])
            delete_results = {}
            for slug in action_args:
                r = grafana.deleteDashboard(slug)
                delete_results[slug] = r
        module.exit_json(changed=True, delete_results=delete_results)
    if run_tests:
        ok, info = slug_test_pass()
        if not ok:
            module.fail_json(msg=info)
    # if text != None:
    #     # module.fail_json(msg=text.decode('utf-8'))
    #     try:
    #         # result=slugify(text.decode('utf-8'))
    #         result=slugify(text)
    #     except Exception as e:
    #         module.fail_json(msg=e.message)
    #     module.fail_json(msg=result)
    
    grafana = Grafana(module, module.params['url'],module.params['username'], module.params['password'])
    resp = grafana.getDashboardList(search_query)
    # module.fail_json(msg="responce=%s" % resp)
    module.fail_json(msg=local_path)
    
    module.exit_json(changed=False)

# slug_test_pass()
# print(json.dumps({
#     "time" : "ok"
# }))

if __name__ == '__main__':
    main()
