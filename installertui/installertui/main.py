import openshift as oc

def filtered_projects(projects):
    filtered = []
    for project in projects:
        if project != "multicluster-engine" and project != "open-cluster-management":
            continue
        filtered.append(project)
    return filtered

def main():
    with oc.tracking() as _:
        mce_version = None
        acm_version = None
        with oc.project("multicluster-engine"):
            mce_version = oc.selector("csv").objects()[0].model.spec.version
        
        with oc.project("open-cluster-management"):
            acm_version = oc.selector("csv").objects()[0].model.spec.version
        
        print(f"MCE Version: {mce_version}")
        print(f"ACM Version: {acm_version}")

        # project_selector = oc.selector("projects")
        # projects = filtered_projects(project_selector.names())
        # for project in projects:
        #     print("-------------------")
        #     print("Project: " + project)
        #     with oc.project(project):
        #         dep_selector = oc.selector("deployments")
        #         print(dep_selector.names())
        # print()
        # with oc.project(projects[0]):
        #     op_selector = oc.selector("csv")
        #     print(op_selector.objects()[0].model.spec.version)

        #     dep_selector = oc.selector("deployments")
        #     deployments = dep_selector.objects()
        #     deployment = deployments[0]
        #     print(f"The project is: {deployment.kind()}/{deployment.name()}")
        #     print(f"With annotations: {deployment.model.metadata.annotations}")
        
if __name__ == "__main__":
    main()