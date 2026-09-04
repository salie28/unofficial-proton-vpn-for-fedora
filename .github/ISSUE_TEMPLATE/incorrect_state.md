---
name: The interface showed the wrong connection state
about: It said Protected when you were not, or the reverse
labels: bug, incorrect-state
---

This is the most serious kind of bug in this project, so it has its own form.

**What the app showed**

**What was actually true**

Output of:

```bash
nmcli -t -f NAME,TYPE,DEVICE,STATE con show --active
ip -br addr show proton0
```

**What led up to it**

A failed connection, a dropped network, a suspend and resume, switching
servers, something else?
