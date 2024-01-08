import openshift as oc

def main():
    with oc.tracking() as _:
        with oc.project("multicluster-engine"):
            mce_version = oc.selector("csv").objects()[0].model.spec.version
            deployments = oc.selector("deployments").objects()
            for deployment in deployments:
                print("--------------------")
                print(f"Deployment: {deployment.kind()}/{deployment.name()}")
                release_version = deployment.model.metadata.annotations["installer.multicluster.openshift.io/release-version"]
                if release_version != mce_version:
                    print(f"Release version mismatch. MCE: {mce_version}, Annotation: {release_version}")
                else:
                    print(f"Release version match. MCE: {mce_version}, Annotation: {release_version}")

        
        with oc.project("open-cluster-management"):
            acm_version = oc.selector("csv").objects()[0].model.spec.version
            deployments = oc.selector("deployments").objects()
            for deployment in deployments:
                print("--------------------")
                print(f"Deployment: {deployment.kind()}/{deployment.name()}")
                release_version = deployment.model.metadata.annotations["installer.open-cluster-management.io/release-version"]
                if release_version != acm_version:
                    print(f"Release version mismatch. ACM: {acm_version}, Annotation: {release_version}")
                else:
                    print(f"Release version match. ACM: {acm_version}, Annotation: {release_version}")
        
if __name__ == "__main__":
    main()