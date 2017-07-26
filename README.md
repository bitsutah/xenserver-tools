# xenserver-tools

vm-backup-xva.py

Is a semi-interactive script that iterates through all running VMs in a Xenserver pool and creates an .xva export to a mountpoint.

The variables at the top of the script are there for you to populate with target info.

The script will look at your iscsi lvm data stores and ask you which one to use for temporary VM storage during the backup.

Tested and seems to work on Xenserver 6.5, 7.0 and 7.2 versions. 

If this thing nukes your production Xenserver pool, and/or ruins every VM you have, that's your fault for running random code you found on the internet.

How it works :
