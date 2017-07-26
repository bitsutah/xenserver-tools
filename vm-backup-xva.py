#!/usr/bin/env python

import subprocess
import sys
import time

sane_vm_number = 50

nfs_target         = "192.168.1.20:/nfs/virtual-machines" #wherever your NFS server:path is to send XVA files.
nfs_mountdir	   = "mnt" #/mnt
nfs_mountpoint     = "backup-nfs-drive-192.168.1.10" #/mnt/backup-nfs-drive-192.168.1.10
nfs_backup_dir     = "backup-dir" #/mnt/backup-nfs-drive-192.168.1.10/backup-dir
ok_to_write_signal = "ok-to-write-here.txt" # a text file to look for on nfs target dir
nfs_min_free_disk  = 500000000 		# .5 TB
export_vm_prefix   = "z-bak-"  # all VMs prefixed with this
export_extension   = ".xva"
export_path        = "/" + nfs_mountdir +"/"+ nfs_mountpoint +"/"+ nfs_backup_dir +"/"
vm_start_with	   = 0  # if you want to start with a different VM to backup (skipping a problem VM)



vm_dict = {}  # will be filled with vms later
temp_vm_sr = ""



def validate_nfs_target():

  print "\nChecking that NFS target is ready..."

  cmd = "ls -1 /%s/%s/%s/%s 2>/dev/null" % (nfs_mountdir,nfs_mountpoint,nfs_backup_dir,ok_to_write_signal)
  check_expected_nfs_target = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split("\n")[0]
  expected_nfs_target = "/" + nfs_mountdir +"/"+ nfs_mountpoint +"/"+ nfs_backup_dir +"/"+ ok_to_write_signal
  if check_expected_nfs_target == expected_nfs_target :
    print "\tNFS mount seems valid. Found %s Continuing..." % ok_to_write_signal
  else :
    print "\tNFS target does not seem to be mounted." 
    print "\tEnsure these settings :"
    print "\t\ttarget: %s" % nfs_target
    print "\t\tmountpoint: /%s/%s" % (nfs_mountdir, nfs_mountpoint)
    print "\t\tcontaining dir: %s" % nfs_backup_dir
    print "\t\tcontaining file: %s" % ok_to_write_signal
    print "\t\t\tmount -t nfs %s /%s/%s" % (nfs_target, nfs_mountdir, nfs_mountpoint)
    print "\t exiting..."
    sys.exit(1)

  cmd = "df | grep \"%s\"" % nfs_mountpoint
  check_nfs_target_disk_space = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split("\n")[0].split(" ")[4]
  if check_nfs_target_disk_space > nfs_min_free_disk :
    print "\tNFS target meets min space requirement. %s bytes vs %s bytes. Continuing..." % (check_nfs_target_disk_space, nfs_min_free_disk)
  else :
    print "\tNFS target does not meet min space requreiment. %s bytes vs %s bytes. exiting..." % (check_nfs_target_disk_space, nfs_min_free_disk)
    sys.exit(1)

  print "\tNFS target meets all requirements.\n"
# end of validate_nfs_target ######################################################################




def select_temporary_vm_sr():
  sr_uuid_arr = []
  chosen_sr_uuid = ""
  print "Getting a list of Storage Repos : xe sr-list ..."
  cmd = "xe sr-list type=lvmoiscsi | grep uuid | sed 's/^.*: //'"  # local lvm and iscsi lvm  
  xe_sr_list_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  sr_arr = xe_sr_list_raw.split("\n")
  print "\tFound %s appropriate Storage Repos" % len(sr_arr)
  sr_counter = 0
  for sr_entry in sr_arr:
    sr_counter = sr_counter + 1
    sr_uuid = sr_entry
    sr_name = ""
    sr_host = ""

    cmd = "xe sr-list uuid=%s | grep name-label | sed 's/^.*: //'" % sr_entry
    xe_sr_list_name_label_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
    sr_name = xe_sr_list_name_label_raw

    cmd = "xe sr-list uuid=%s | grep host | sed 's/^.*: //'" % sr_entry
    xe_sr_list_host_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
    sr_host = xe_sr_list_host_raw
    sr_uuid_arr.append(sr_uuid)
    print "\t" + str(sr_counter)  +" : " + sr_uuid + " \"" + sr_name + "\" " + sr_host

  print "\t"
  
  choice = input("\tWhich SR do you want to place the temporary export VM? : ")
  choice = choice - 1

  if choice < 0 or choice >= len(sr_uuid_arr) :
    print "\tThis choice is nonsense."
    sys.exit(1)

  chosen_sr_uuid = sr_uuid_arr[choice]
  print "\tSR chosen:" + chosen_sr_uuid


  cmd = "xe sr-list uuid=%s | grep name-label" % chosen_sr_uuid 
  chosen_sr_doublecheck_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  print "\t" + chosen_sr_doublecheck_raw

  if raw_input("\t\tDoes this look copacetic? y/n : ") != "y" :
    sys.exit(1)

  return chosen_sr_uuid

# end of select_temporary_vm_sr ####################################################################




# function takes a VM uuid and removes all thie NICs (VIFs) from it.
def remove_nics_from_vm(vm_uuid):
 
  vif_arr = []
  xe_vif_count = 0

  vm_nic_count = 1 #assume it has a nic for exit purposes	
  sane_nic_max = 3 #if the VM has more than this many nics, something spishus.

  # is this even a uuid?
  if len(vm_uuid) != 36:
    print "   the parameter is NOT a uuid. exiting! "
    sys.exit(1)

  # is the uuid actually a sensible VM?
  cmd = "xe vm-list uuid=%s is-control-domain=false" % vm_uuid
  check_vm_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split("\n")[0].strip().split(":")[1].strip()
  if vm_uuid != check_vm_uuid :
    print "  ! something is wrong. the uuid doesn't match a sensible VM. exiting !"
    sys.exit(1)
    return False
  check_vm_name_label = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split("\n")[1].strip().split(":")[1].strip()
  
  # get a list of vifs and make
  cmd = "xe vif-list vm-uuid=%s | grep \"^uuid ( RO)\"" % vm_uuid
  xe_vif_list_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  if len(xe_vif_list_raw) == 0:
    print "\t\t\t\tVM has no NICs"
    return True
  xe_vif_list_arr = xe_vif_list_raw.split("\n")
  xe_vif_count = len(xe_vif_list_arr)

  #sanity checking
  if xe_vif_count < 1 or xe_vif_count > sane_nic_max:
    print "   ! something is wrong with the number of nics on this VM. exiting !"
    return False

  print "\t\t\t\txe states this VM has %s network interfaces." % xe_vif_count

  #check xe raw results, make into list of nic uuids, check them for correct VM.
  for vif in xe_vif_list_arr:
    vif_uuid = vif.strip().split(":")[1].strip()
    cmd = "xe vif-list uuid=%s | grep vm-uuid" % vif_uuid
    check_vif_vm_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split(":")[1].strip()
    print "\t\t\t\tvif %s" % ( vif_uuid )
    #vif_arr.append(vif_uuid)
    if check_vif_vm_uuid != vm_uuid:
      print "   ! error. the vm uuid from the VIF doesn't match the vm uuid you are working with. exiting!"
      return False
    vif_arr.append(vif_uuid)
  if xe_vif_count !=  len(vif_arr):
    print "   ! error. the VIF count for this VM changed or doesn't make sense after checks. exiting!" 
    return False

  for vif_uuid in vif_arr:
    print "\t\t\t\tRemoving vif %s " % vif_uuid
    cmd = "xe vif-destroy uuid=%s" % vif_uuid
    subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()

  #check nic list again, good if 0 nics left.
  cmd = "xe vif-list vm-uuid=%s | grep \"^uuid ( RO)\"" % vm_uuid
  xe_vif_list_raw = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()

  if len(xe_vif_list_raw) == 0:
    print "\t\t\t\tVM has 0 network interfaces."
    return True
  print "  ! something went wrong removing interfaces ! "
  return False
# end of nic remover code #########################################################################





# exports temporary VM to an .xva on NFS share
def export_vm_to_xva(vm_uuid) :
  print "\t\t\tExporting VM UUID %s " % vm_uuid
  cmd = "xe vm-list  is-control-domain=false uuid=%s power-state=halted | grep %s" % (vm_uuid , export_vm_prefix)
  xe_vm_list_raw =  subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split(":")[1].strip()
  vm_name_to_export = xe_vm_list_raw
  cmd = "xe vm-list  is-control-domain=false name-label=%s | grep power-state" % vm_name_to_export
  xe_is_vm_halted = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split(":")[1].strip()
  if xe_is_vm_halted != "halted" :
    print "\t\t\t\t%s is not halted. This doesn't make sense. Exiting!" % vm_name_to_export
    exit(1) 
  cmd = "xe vm-export vm=%s filename=%s%s%s" % (vm_name_to_export, export_path, vm_name_to_export, export_extension)
  print "\t\t\t\t%s%s%s" % ( export_path, vm_name_to_export, export_extension )
  xe_xva_export_res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  print "\t\t\t\t\t%s" % xe_xva_export_res
# end of VM exporter #########################################################################






# deletes temporary VM
def delete_temp_vm(vm_uuid) :
  print "\t\t\tDeleting temporary VM UUID %s " % vm_uuid
  cmd = "xe vm-list  is-control-domain=false uuid=%s power-state=halted | grep %s" % (vm_uuid , export_vm_prefix)
  xe_vm_list_raw =  subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split(":")[1].strip()
  vm_name_to_export = xe_vm_list_raw
  cmd = "xe vm-list  is-control-domain=false name-label=%s | grep power-state" % vm_name_to_export
  xe_is_vm_halted = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip().split(":")[1].strip()
  if xe_is_vm_halted != "halted" :
    print "\t\t\t\t%s is not halted. This doesn't make sense. Exiting!" % vm_name_to_export
    exit(1)
  #cmd = "xe vm-destroy uuid=%s" % vm_uuid # leaves VDI
  cmd = "xe vm-uninstall force=true vm=%s" % vm_name_to_export
  xe_vm_destroy_res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
# end of VM deleter #########################################################################






#main stuff =====================================================

print "\n=== vm cloner script ===\n"

validate_nfs_target()
sr_uuid = select_temporary_vm_sr()

print "\nGetting list of VMs."
cmd = "xe vm-list power-state=running is-control-domain=false"
xe_res = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
xe_arr =  xe_res.split("\n\n")
xe_vm_count = len(xe_arr)
print "\txe CLI says we have %s running vms " % xe_vm_count

# fill the dictionary with the vms from the xe vm-list output.
for xe_entry in xe_arr:
  entry_parts = xe_entry.strip().split("\n")
  uuid = entry_parts[0].strip().split(":")[1].strip()
  name_label = entry_parts[1].strip().split(":")[1].strip()
  if len(uuid) != 36:
    print "   whatever that is, its not a uuid! exiting!!1!"
    sys.exit(1)
  if len(name_label) < 2 or len(name_label) > 30:
    print "   that name_label looks 'spishus!"
    sys.exit(1)
  vm_dict[uuid] = name_label

vm_dict_count = len(vm_dict)
if vm_dict_count != xe_vm_count or vm_dict_count < 0 or vm_dict_count > sane_vm_number:
  print "   ! something doesn't make sense. vm count is wrong or not sane. exiting! "
  sys.exit(1)


current_vm_number = 0

for vm_uuid, vm_name_label in vm_dict.iteritems() :

  current_vm_number += 1

  if current_vm_number < vm_start_with :
    continue
  
 
  print "\t\tWorking with vm %s : %s %s " % ( current_vm_number, vm_uuid , vm_name_label )
  cmd = "xe vm-list  is-control-domain=false uuid=%s | grep name-label" % vm_uuid
  vm_info = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  check_vm_name = vm_info.strip().split(":")[1].strip()
  if check_vm_name != vm_name_label :
    print "  ! the vm names don't match. exiting!!1!"
    sys.exit(1)

  print "\t\t\tTaking snapshot"
  snap_stamp = time.strftime("%Y-%m-%d-%H%M")
  cmd = "xe vm-snapshot vm=%s new-name-label=%s" % ( vm_uuid , vm_name_label+"-snap-"+snap_stamp  )
  snap_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  
  # Making sure this snapshot belongs to the right vm
  cmd = "xe snapshot-list uuid=%s snapshot-of=%s | grep uuid | sed 's/^.*: //'" % ( snap_uuid , vm_uuid )
  check_snap_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  
  if snap_uuid != check_snap_uuid :
    print "   ! the uuid's don't match. something is wrong. exiting!!"
    sys.exit(0)
  print "\t\t\tSnapshot successfull, uuid : %s " % snap_uuid

  print "\t\t\tCopying snapshot to a template on an SR : %s " % sr_uuid
  cmd = "xe snapshot-copy new-name-label=%s uuid=%s sr-uuid=%s" % ( vm_name_label+"-templ-"+snap_stamp , snap_uuid , sr_uuid )
  template_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  print "\t\t\tTemplate uuid is : %s" % template_uuid
  

  print "\t\t\tCreating temporary VM based on that template"
  cmd = "xe vm-install new-name-label=%s template=%s" % ( export_vm_prefix + vm_name_label + "-" +snap_stamp , template_uuid )
  temp_vm_uuid = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()
  print "\t\t\tTemporary VM uuid is : %s " % temp_vm_uuid 

  print "\t\t\tRemoving VM host affinity"
  cmd = "xe vm-param-set uuid=%s affinity=" % temp_vm_uuid
  xe_vm_remove_affinity = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()

  print "\t\t\tCleanup"

  print "\t\t\t\tDeleting snapshot (xe snapshot-uninstall) : %s" %  snap_uuid
  cmd = "xe snapshot-uninstall force=true snapshot-uuid=%s" %  snap_uuid
  xe_snap_del_response = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()

  print "\t\t\t\tDeleting template (xe template-uninstall) : %s" %  template_uuid
  cmd = "xe template-uninstall force=true template-uuid=%s" %  template_uuid
  xe_temp_del_response = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE).stdout.read().strip()

  print "\t\t\tPost processing"
  print "\t\t\t\tRemoving the NICs from the cloned vm to avoid accidents"
  if not remove_nics_from_vm(temp_vm_uuid):
    print "   ! something went wrong removing NICs! exiting!"
    sys.exit(1)



  export_vm_to_xva(temp_vm_uuid)

  delete_temp_vm(temp_vm_uuid)
  
  
  print "\t\t\t=== Done with this VM ===\n"
  # each VM loop #########################################################################


print "\nvm cloner done. exiting!\n\n"
