from datetime import datetime
import traceback
import subprocess
import os 
import sys
import json
import socket
import time
import csv
import logging

###Global Variables###
# bash scripting
global shell
shell = '#!/bin/bash'
global cpprofile
cpprofile = '''source /etc/profile.d/CP.sh
source /etc/profile.d/vsenv.sh
source $MDSDIR/scripts/MDSprofile.sh
source $MDS_SYSTEM/shared/mds_environment_utils.sh
source $MDS_SYSTEM/shared/sh_utilities.sh
'''
# timestamp 
global now
nowtmp = datetime.now()
now = nowtmp.strftime("%m-%d-%y_%H-%M-%S")
# filepaths
global gwpath
gwpath = '/home/admin/elco1001/gw_bulk'
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


logging.basicConfig(level=logging.DEBUG,
            format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
            datefmt='%a, %d %b %Y %H:%M:%S',
            filename=f"{gwpath}/log.log",
            filemode='w')

class Log:
    @classmethod
    def debug(cls, msg):
        logging.debug(msg)

    @classmethod
    def info(cls, msg):
        logging.info(msg)

    @classmethod
    def error(cls, msg):
        logging.error(msg)

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

    global username, password, targetdomain, command

    username = question("Username")
    password = question("Password")
    targetdomain = question("'All' Domains or IP of specific Domain")
    command = question("Command to run on all gateways")

    formatanswer = f"""username = {username}
password = {password}
domain = {targetdomain}
command = {command}
"""  

    result = question(f"\n{formatanswer}\nIs this information correct? (y/n)")   
    if result == "n":
        askConfig()
    elif result == "y": 
        print("\nContinuing... \n")

# make log directory / clear old log files
def mkdir():

    Log.info(f'[ mkdir | {gwpath} | {gwbin} | {gwout}]\n')

    if os.path.isdir(gwpath) and os.path.isdir(gwbin) and os.path.isdir(gwout):
        Log.info(f'... Exists!\n')
    else:
        Log.info(f'... Does not exist\n')
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
./gw_bulk_v2.py OPTIONS

Options:
-d = Enable Debug (debug = 1)
-h = Help Menu

Notes: 
CPRID (NULL BUF) troubleshooting sk174346

Scope: 
For MDM only. 
            

[ Description ]

Execute commands across all gateways on MDM.Only runs on MDM.


[ Instructions ]

1: Provide Username and Password of MDM administrator as well as command to run on all gateways.

2: /var/log/gw_bulk - main output directory

3: /var/log/gw_bulk/output/

gw_stdout.json - main output file

gw_inventory.json - all domains -> all managed gateways

gw_mapping.json - responsive gateway -> managed domain

gw_failures.json - connectivity failures, CPRID version issues


[ Performance ]

Takes about 20 minutes to run 'uptime' on 300+ gateways


[ Troubleshooting ]

(NULL BUF) = CPRID version issue or general CPRID error (sk174346)''')
        quit() 
    elif len(sys.argv) > 1 and sys.argv[1] == "-d":
        Log.debug('\n[ Debug Mode Enabled ]\n') 
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
    
    return cmdout

# make list of CMA IP's 
def domains():
    
    global domainlist
    
    if targetdomain == 'all': 
        dmcmd = "mdsstat | grep -i cma | awk '{print $6}'"
        script = f'{gwbin}/tmp_gw_bulk_domains_list.sh'
        domainlist = runcmd(dmcmd, script).split()
        if debug == 1:
            Log.info(f"[ DOMAIN LIST ]\n{domainlist}\n")
    else: 
        domainlist = [targetdomain]

# generate list of gateways per CMA
def gateways(): 

    try:
        for domain in domainlist: 
            inventory[domain] = []
            Log.info(f"[gateways] : queryDB_util : {domain}\n")
            cmdlist =[
f'''mdsenv {domain}
(echo {domain};  echo {username}; echo {password}; echo "-t network_objects -s class='cluster_member'|type='gateway_ckp'|type='cluster_member' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' 
''',
f'''mdsenv {domain}
(echo {domain};  echo {username}; echo {password}; echo "-t network_objects -s class='gateway_ckp'&location='internal' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' | grep -v 'ipaddr_from_mac:' 
''' ]       
            count = 0
            for cmd in cmdlist: 
                count += 1
                script = f'{gwbin}/tmp_gateways_{count}_{domain}_tmp.sh'
                gwlist = runcmd(cmd, script).split()
                for i in gwlist: 
                    inventory[domain].append(i)
                
    except Exception as e: 
        Log.error(traceback.print_exc())
        Log.error(f"[gateways] : Error {e}\n")


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
        for domain in inventory.keys():
            for gwip in inventory[domain]:
                if testconn(gwip, 18208, tmout) != 0:
                    failcount += 1
                    Log.info(f"[testconn] : Check connectivity : {gwip}:18208 : Count {failcount}\n")
                    failures[gwip] = f"No connectivity on port 18208, Count {failcount}"
                else:
                    count += 1
                    Log.info(f"[output] : {command} : {domain} | {gwip} : Count {count}\n")
                    # segfault (null buff) from os causes subprocess to fail
                    # and causes the entire script to exit, try/except does not work
                    # requires 'exit 0' at end of bash script
                    cmd = f'''mdsenv {domain}
cprid_util -server {gwip} -verbose rexec -rcmd bash -c "{command}"
exit 0'''
                    script = f'{gwbin}/tmp_bash_gw-{gwip}_tmp.sh'
                    result = runcmd(cmd, script)
                    
                    if len(result) == 0:
                        errorcount += 1
                        Log.info(f"[output] : Output Empty : {gwip} : Count {errorcount}\n")
                        failures[gwip] = f"Empty Output {errorcount}"
                    elif 'NULL' in result:
                        errorcount += 1
                        Log.info(f"[output] : (NULL BUF) : {gwip} : Count {errorcount}\n")
                        failures[gwip] = f"CPRID Error : (NULL BUF) : Count {errorcount}"
                    else:
                        stdout[gwip] = result.strip()

    except Exception as e:
        Log.error(traceback.print_exc())
        Log.error(f"[output] : Error : {e}\n")


def writefiles():

    # creating mapping of gateway to domain for later use
    try:
        for gw in stdout.keys(): 
            for key,value in inventory.items(): 
                if gw in value: 
                    mapping[gw] = [key] 
    except Exception as e:
        Log.error(f"Error {e}\n")
    
    # domain -> gateways (all gateways)
    with open(f'{gwout}/gw_inventory.json', 'w') as f:
        f.write(json.dumps(inventory, indent=4, sort_keys=False))
    
    # gateway -> domain (succsessful gateways)
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
    Log.info("\n\n[ No Output or CPRID issue ]\n\n")
    try:
        for fail,reason in failures.items():
            if 'NULL' in reason or 'Empty' in reason:
                for key,value in inventory.items():
                    if fail in value:
                        Log.info(f"Gateway {fail} : Domain {key}")
    except Exception as e:
        Log.error(f"[ report ] : Error {e}\n")
    
    # reverse lookup of inventory for gateways with connection issues
    Log.info("\n\n[ Failed to connect to Gateway. ]\n\n")
    try:
        for fail,reason in failures.items():
            if 'connectivity' in reason:
                for key,value in inventory.items(): 
                    if fail in value:
                        Log.info(f"Gateway {fail} : Domain {key}")
    except Exception as e:
        Log.error(f"[ report ] : Error {e}\n")
    
    #end time
    endtime = time.time()
    totaltime = endtime - starttime
    Log.info(f"\n Total Run Time : {totaltime} seconds")


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
    
    # get domains list 
    domains()
    
    # get list of gateways from domains
    gateways()

    # send command and gather output
    output()


if __name__ == "__main__": 
    
    try:
        #time start
        starttime = time.time()
        Log.info(f"Start Time: {starttime}")
        cleanup() 
        main()
    except Exception as e:
        Log.error(f"[main] : Error : {e}\n")
        Log.error(traceback.print_exc())
    finally:
        writefiles()
        report()
        end()

