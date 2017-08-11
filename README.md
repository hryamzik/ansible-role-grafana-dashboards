# grafana-dashboards

Ansible role designed to sync grafana dashbroards with local directory.

### Limitations

Only DB dashboards are supported. Only grafana installations with only DB dashboards should work properly.

### Notes

- Initially dashboards are identified by slug names. Then a mapping to IDs is saved for each grafana instance.
- Dashboards are compared by `version`. Version is uniq for each grafana instance so this information is stored in mappings file as well.
- You can put dashboards exported via UI to the project.
- It may not be safe to run this module across multiple hosts (with `with_items`) as mapping file is changed on each action.
- Complicated dashboard titles could cause issues

### TODO

- fix test option
- fix slugify
- lock mappings file
- implement option to sync home dashboard
