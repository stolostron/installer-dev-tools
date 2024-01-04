import openshift as oc

def main():
    with oc.tracking() as _, oc.timeout(10*60):
        print('OpenShift client version: {}'.format(oc.get_client_version()))

        project_selector = oc.selector("projects")
        print("Project names: " + str(project_selector.qnames()))
        
if __name__ == "__main__":
    main()