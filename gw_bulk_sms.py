from datetime import datetime
import traceback
import subprocess
import os 
import sys
import json
import socket
import time
import csv

###Global Variables###
# bash scripting
global shell
shell = '#!/bin/bash'
global cpprofile
cpprofile = '''source /etc/profile.d/CP.sh
source /etc/profile.d/vsenv.sh
'''
# timestamp 
global now
nowtmp = datetime.now()
now = nowtmp.strftime("%m-%d-%y_%H-%M-%S")
# filepaths
global gwpath 
gwpath = '/var/log/gw_bulk'
global gwbin
gwbin = f'{gwpath}/scripts'
global gwout
gwout = f'{gwpath}/output'
# dictionaries 
global mapping
mapping = {}
global gmap 
gmap = {}
global failures
failures = {}
global inventory 
inventory = {} 
global stdout
stdout = {}
# connectivity timeout
global tmout 
tmout = 5

###Debugging Functions###
# pause script, take any input to continue 
def pause_debug():
    input("[ DEBUG ] Press any key to continue...\n\n")   

# script exit 
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

    global username, password, ipaddress, command

    username = question("Username")
    password = question("Password")
    ipaddress = question("IP Address of Management Server")
    command = question("Command to run on all gateways")
    

    formatanswer = f"""username = {username}
password = {password}
IP Address = {ipaddress}
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
        print('''[ Help Menu ]

Support: 
cellis@checkpoint.com

Usage: 
./gw_bulk_sms.py OPTIONS

Options:
-d = Enable Debug (debug = 1)
-h = Help Menu

Notes: 
CPRID (NULL BUF) troubleshooting sk174346

Scope: 
For SMS only. 
            

[ Description ]

Execute commands across all gateways on MDM.Only runs on MDM.


[ Instructions ]

1: Provide Username/Password/IP Address of SMS administrator as well as command to run on all gateways.

2: /var/log/gw_bulk - main output directory

3: /var/log/gw_bulk/output/

gw_stdout.json - main output file

gw_inventory.json - SMS -> all managed gateways

gw_mapping.json - responsive gateway -> managed sms

gw_failures.json - connectivity failures, CPRID version issues


[ Performance ]

Takes about 20 minutes to run 'uptime' on 300+ gateways


[ Troubleshooting ]

(NULL BUF) = CPRID version issue or general CPRID error (sk174346)''')
        quit() 
    elif len(sys.argv) > 1 and sys.argv[1] == "-d":
        print('\n[ Debug Mode Enabled ]\n') 
        global debug
        debug = 1
    else: 
        end()
    
    return debug

# create bash scripts to run against mds
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
        cmdout = subprocess.check_output(script, shell=True, text=True, timeout=30)
    except Exception as e:
        traceback.print_exc()
        print(f"[runcmd] : Error : {e}")

    if debug == 1: 
        print(f"[ runcmd ]\n{cmdout}\n\n")
        pause_debug()
        os.system(f"rm -v {script}")
    else:
        os.system(f"rm {script}")
    
    return cmdout

# generate list of gateways for SMS
def gateways(): 

    try:
        print(f"[gateways] : queryDB_util : {ipaddress}\n")
        cmd = f'''(echo {ipaddress};  echo {username}; echo {password}; echo "-t network_objects -s class='cluster_member'|type='gateway_ckp'|type='cluster_member' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' '''
        script = f'{gwbin}/tmp_gateways_{ipaddress}_tmp.sh'
        gwlist = runcmd(cmd, script).split()

        inventory[ipaddress] = []
        for i in gwlist: 
            inventory[ipaddress].append(i)

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
    failcount = 0
    errorcount = 0
    try:
        for sms in inventory.keys():
            for gwip in inventory[sms]:
                if testconn(gwip, 18208, tmout) != 0:
                    failcount += 1
                    print(f"[testconn] : Check connectivity : {gwip}:18208 : Count {failcount}\n")
                    failures[gwip] = f"No connectivity on port 18208, Count {failcount}"
                else:
                    count += 1
                    print(f"[output] : {command} : {sms} | {gwip} : Count {count}\n")
                    # segfault (null buff) from os causes subprocess to fail
                    # and causes the entire script to exit, try/except does not work
                    # requires 'exit 0' at end of bash script
                    cmd = f'''cprid_util -server {gwip} -verbose rexec -rcmd bash -c "{command}"
exit 0'''
                    script = f'{gwbin}/tmp_bash_gw-{gwip}_tmp.sh'
                    result = runcmd(cmd, script)
                    
                    if len(result) == 0:
                        errorcount += 1
                        print(f"[output] : Output Empty : {gwip} : Count {errorcount}\n")
                        failures[gwip] = f"Empty Output {errorcount}"
                    elif 'NULL' in result:
                        errorcount += 1
                        print(f"[output] : (NULL BUF) : {gwip} : Count {errorcount}\n")
                        failures[gwip] = f"CPRID Error : (NULL BUF) : Count {errorcount}"
                    else:
                        stdout[gwip] = result.strip()

    except Exception as e:
        traceback.print_exc()
        print(f"[output] : Error : {e}\n")


def writefiles():

    # creating mapping of gateway to sms for later use
    try:
        for gw in stdout.keys(): 
            for key,value in inventory.items(): 
                if gw in value: 
                    mapping[gw] = [key] 
    except Exception as e:
        print(f"Error {e}\n")
    
    # sms -> gateways (all gateways)
    with open(f'{gwout}/gw_inventory.json', 'w') as f:
        f.write(json.dumps(inventory, indent=4, sort_keys=False))
    
    # gateway -> sms (succsessful gateways)
    with open(f'{gwout}/gw_mapping.json', 'w') as f:
        f.write(json.dumps(mapping, indent=4, sort_keys=False))        
        
    #gateway fail reason (failed gateways)
    with open(f'{gwout}/gw_failures.json', 'w') as f:
        f.write(json.dumps(failures, indent=4, sort_keys=False))
    
    # gateway command output
    with open(f'{gwout}/gw_stdout.json', 'w') as f:
        f.write(json.dumps(stdout, indent=4, sort_keys=False))  
    
    # make csv of stdout information 
    fcsv = f'{gwout}/gw_stdout.csv'
    with open(fcsv, 'w') as f:
        w = csv.writer(f)
        w.writerows(stdout.items())


def report(): 
    
    # reverse lookup of inventory for gateways with cprid issues 
    print("\n\n[ No Output or CPRID issue ]\n\n")
    try:
        for fail,reason in failures.items():
            if 'NULL' in reason or 'Empty' in reason:
                for key,value in inventory.items():
                    if fail in value:
                        print(f"Gateway {fail} : SMS {key}")
    except Exception as e:
        print(f"[ report ] : Error {e}\n")
    
    # reverse lookup of inventory for gateways with connection issues
    print("\n\n[ Failed to connect to Gateway. ]\n\n")
    try:
        for fail,reason in failures.items():
            if 'connectivity' in reason:
                for key,value in inventory.items(): 
                    if fail in value:
                        print(f"Gateway {fail} : SMS {key}")
    except Exception as e:
        print(f"[ report ] : Error {e}\n")
    
    #end time
    endtime = time.time()
    totaltime = endtime - starttime
    print(f"\n Total Run Time : {totaltime} seconds")


def cleanup():
    # remove undeleted tmp scripts
    os.system(f"rm -v {gwbin}/*")


def main(): 
    
    # enable debug mode or not
    global debug
    if len(sys.argv) > 1: 
        helpmenu()
    else:
        debug = 0
    
    # get user configuration 
    askConfig()
    
    # create direcotries
    mkdir() 
    
    # get list of gateways from sms
    gateways()

    # send command and gather output
    output()


if __name__ == "__main__": 
    
    try:
        #time start
        starttime = time.time()
        main()
    except Exception as e:
        print(f"[main] : Error : {e}\n")
        traceback.print_exc()
    finally:
        writefiles()
        report()
        cleanup() 
        end()
