#!/usr/bin/env python

import subprocess
import sys

prefix = sys.argv[1]
text=subprocess.check_output(['ovs-vsctl', 'show'])
temp= [int(el[len(prefix)+1:-1]) for el in text.split() if prefix in el]
res = (max(temp)+1) if temp else 0
print res
