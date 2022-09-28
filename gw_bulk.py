from datetime import datetime
import traceback
import subprocess
import os 
import sys
import json
import socket
import time
import csv 

#Global Variables
global shell
shell = '#!/bin/bash'
global cpprofile
cpprofile = '''source /etc/profile.d/CP.sh
source /etc/profile.d/vsenv.sh
source $MDSDIR/scripts/MDSprofile.sh
source $MDS_SYSTEM/shared/mds_environment_utils.sh
source $MDS_SYSTEM/shared/sh_utilities.sh
'''
global now
nowtmp = datetime.now()
now = nowtmp.strftime("%m-%d-%y_%H-%M-%S")
global gwpath
gwpath = '/var/log/gw_bulk'
global gwbin
gwbin = f'{gwpath}/scripts'
global gwout
gwout = f'{gwpath}/output'
global failures
failures = {}
global verified
verified = {}
global inventory 
inventory = {} 
global stdout
stdout = {}

###Debugging Functions###
# take any input to pause debug 
def pause_debug():
    input("[ DEBUG ] Press any key to continue...\n\n")   


def end(): 
    sys.exit(0)

#input validation for questions
def question(stuff):
    while True:
        answer = input(f"\n{stuff}:\n")
        if len(answer) != 0:
            False
            return answer 


# ask user for configuration 
def askConfig():

    print("\n[ Provide Configuration ]\n")

    global username, password, command

    username = question("Username")
    password = question("Password")
    command = question("Command to run on all gateways")

    formatanswer = f"""username = {username}
password = {password}
command = {command}
"""  

    result = question(f"\n{formatanswer}\nIs this information correct? (y/n)")   
    if result == "n":
        askConfig()
    elif result == "y": 
        print("\nContinuing... \n")

# make log directory / clear old log files
def mkdir():

    print(f'[ mkdir | {gwpath} | {gwbin} | {gwout}]\n')

    if os.path.isdir(gwpath) and os.path.isdir(gwbin) and os.path.isdir(gwout):
        print(f'... Exists!\n')
    else:
        print(f'... Does not exist\n')
        os.system(f'mkdir -v {gwpath}')
        os.system(f'mkdir -v {gwbin}')
        os.system(f'mkdir -v {gwout}')
    

#help menu
def helpmenu():

    if len(sys.argv) > 1 and sys.argv[1] == "-h": 
        print(
            '''
            [ Help Menu ]
            
            Usage: 
            ./gw_bulk_v2.py OPTIONS
            
            Options:
            -d = Enable Debug (debug = 1)
            -h = Help Menu
            
            Notes: 
            Coming soon... 
            '''
        )
        quit() 
    elif len(sys.argv) > 1 and sys.argv[1] == "-d":
        print('\n[ Debug Mode Enabled ]\n') 
        global debug
        debug = 1
    else: 
        end()
    
    return debug


# create scripts to run on mds
def runcmd(cmd, script):

    bash=f"""{shell} 
{cpprofile} 
{cmd} 
"""

    if debug == 1:
        print(f'[ contents ]\n{bash}\n') 
        print(f'[ script]\n{script}\n')
        print('[[ Does everything look right? ]]\n')
        pause_debug()

    with open(script, 'w') as f: 
        f.write(bash)

    os.system(f"chmod +x {script}")
    
    try:
        result = subprocess.check_output(script, shell=True, text=True, timeout=30)
    except Exception as e:
        traceback.print_exc()
        print(f"[runcmd] : Error : {e}")

    if debug == 1: 
        print(f"[ runcmd ]\n{result}\n\n")
        pause_debug()
        os.system(f"rm -v {script}")
    else:
        os.system(f"rm {script}")
    
    return result


def domains():
    
    global domainlist
    dmcmd = "mdsstat | grep -i cma | awk '{print $6}'"
    script = f'{gwbin}/tmp_gw_bulk_domains_list.sh'
    domainlist = runcmd(dmcmd, script).split()
    print(f"[ DOMAIN LIST ]\n{domainlist}\n")


# generate list of all gateways
def gateways(): 

    try:
        for domain in domainlist: 
            print(f"[gateways] : queryDB_util : {domain}\n")
            cmd = f'''mdsenv {domain}
(echo {domain};  echo {username}; echo {password}; echo "-t network_objects -s class='cluster_member'|type='gateway_ckp'|type='cluster_member' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' 
'''
            script = f'{gwbin}/tmp_gateways_{domain}_tmp.sh'
            gwlist = runcmd(cmd, script).split()

            inventory[domain] = []
            for i in gwlist: 
                inventory[domain].append(i)
    except Exception as e: 
        traceback.print_exc()
        print(f"[gateways] : Error {e}\n")

    print(f"[gateways] : Gateway List Complete")


def testconn(ip, port, tmout): 

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(tmout)
    result = sock.connect_ex((ip,int(port)))
    return result


def output(): 
    
    count = 0
    fcount = 0
    ecount = 0
    try:
        for domain in inventory.keys():
            for gwip in inventory[domain]:
                if testconn(gwip, 18208, 3) != 0:
                    fcount += 1
                    print(f"[testconn] : Check connectivity : {gwip}:18208 : Count {fcount}\n")
                    failures[gwip] = f"No connectivity on port 18208, Count {fcount}"
                else:
                    count += 1
                    print(f"[output] : {command} : {domain} | {gwip} : Count {count}\n")
                    # segfault (null buff) from os causes subprocess to fail
                    # and causes the entire script to exit, try/except does not work
                    # needs 'exit 0' at end of bash script
                    cmd = f'''mdsenv {domain}
cprid_util -server {gwip} -verbose rexec -rcmd bash -c "{command}"
exit 0'''
                    script = f'{gwbin}/tmp_info_gw-{gwip}_tmp.sh'
                    result = runcmd(cmd, script)
                    
                    if len(result) < 5: 
                        ecount += 1
                        print(f"[output] : Output Empty : {gwip} : Count {ecount}\n")
                        failures[gwip] = f"Empty List {ecount}"
                        stdout[gwip] = ''
                    else:
                        stdout[gwip] = result.strip()

    except Exception as e:
        traceback.print_exc()
        print(f"[output] : Error : {e}\n")

    try:
        for key,value in stdout.items():
            if len(value) != 0:
                verified[key] = "True"
            else:
                verified[key] = "False"
                
    except Exception as e:
        traceback.print_exc()
        print(f"[output] : Error : {e}\n")


def cleanup():
    # remove undeleted tmp scripts
    os.system(f"rm -v {gwbin}/*")


def main(): 
    
    # run debug mode or not
    global debug
    if len(sys.argv) > 1: 
        helpmenu()
    else:
        debug = 0
    
    # get user configuration 
    askConfig()
    
    # create direcotry 
    mkdir() 
    
    # domains list 
    domains()
    
    # get list of domains and gateways
    gateways()

    # get output
    output()
    


if __name__ == "__main__": 
    
    try:
        #time start
        starttime = time.time()
        main()
    except Exception as e:
        traceback.print_exc()
        print(f"[main] : Error : {e}\n")
    finally:
        
        mapping = {}

        try:
            for vgw in verified.keys(): 
                for key,value in inventory.items(): 
                    if vgw in value: 
                        mapping[vgw] = [key] 
        except Exception as e:
            print(f"Error {e}\n")     
        
        print("\n\n[ No Output or CPRID issue ]\n\n")
        for key,value in verified.items():
            if value == "False": 
                print(f"Gateway {key} : Domain {mapping[key]}")
        
        fconnect = {}
        print("\n\n[ Failed to connect to Gateway. ]\n\n")
        try:
            for fail,reason in failures.items():
                if 'connectivity' in reason:
                    for key,value in inventory.items(): 
                        if fail in value:
                            print(f"Gateway {fail} : Domain {key}")
        except Exception as e:
            print(f"Error {e}\n")
        
        
        # domain -> gateways 
        with open(f'{gwout}/gw_inventory.json', 'w') as f:
            f.write(json.dumps(inventory, indent=4, sort_keys=False))
        
        # gateway -> domain
        with open(f'{gwout}/gw_mapping.json', 'w') as f:
            f.write(json.dumps(mapping, indent=4, sort_keys=False))        
        
        # output successful
        with open(f'{gwout}/gw_successful.json', 'w') as f:
            f.write(json.dumps(verified, indent=4, sort_keys=False))
            
        #record failures 
        with open(f'{gwout}/gw_failures.json', 'w') as f:
            f.write(json.dumps(failures, indent=4, sort_keys=False))
        
        # gateway -> output
        with open(f'{gwout}/gw_stdout.json', 'w') as f:
            f.write(json.dumps(stdout, indent=4, sort_keys=False))  
            
        fcsv = f'{gwout}/gw_stdout.csv'
        with open(fcsv, 'w') as f:
            w = csv.writer(f)
            w.writerows(stdout.items())


        #end time
        endtime = time.time()
        totaltime = endtime - starttime
        print(f"\n Total Run Time : {totaltime} seconds")
        
        # remove leftover files
        cleanup() 
    
        end()

