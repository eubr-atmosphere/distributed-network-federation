#!/usr/bin/env python

start_string = "Build-Depends:"
end_string = "Standards-Version:"
is_started = False
res = ""
with open("debian/control") as fh:
	for line in fh:
		if start_string in line:
			is_started=True
			line=line[len(start_string):]
		elif end_string in line:
			break
        	if is_started:
			res+=line.replace(","," ").split()[0] + " "
print(res)
