import openshift as oc

def filtered_projects(projects):
    filtered = []
    for project in projects:
        if "openshift" in project:
                continue
        if "kube" in project:
            continue
        if "default" in project:
            continue
        filtered.append(project)
    return filtered

def main():
    with oc.tracking() as _:
        project_selector = oc.selector("projects")
        projects = filtered_projects(project_selector.names())
        for project in projects:
            print("-------------------")
            print("Project: " + project)
            with oc.project(project):
                dep_selector = oc.selector("deployments")
                print(dep_selector.qnames())
        print()
        
if __name__ == "__main__":
    main()