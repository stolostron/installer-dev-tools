# Open the OpenShift web console in your browser
open-console:
    {{ if os() == "macos" { "open" } else { "xdg-open" } }} $(oc whoami --show-console) 2>/dev/null