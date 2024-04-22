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
import argparse
from argparse import RawTextHelpFormatter
import smtplib
from email.message import EmailMessage

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
global gwpath, gwbin, gwout
gwpath = os.path.dirname(os.path.abspath(__file__))
gwbin = f'{gwpath}/scripts'
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
            filename=f'{gwpath}/log.log',
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
    
def args(): 
    parser = argparse.ArgumentParser(add_help=False,
        formatter_class=RawTextHelpFormatter, 
        prog=f'python3 {os.path.basename(__file__)}',
        description='Collect or implement configuration from all gateways',
        epilog=f'''
[Support]
cellis@checkpoint.com

[Notes]
CPRID (NULL BUF) troubleshooting sk174346

[Scope]
MDM only. 

[Instructions]
1: Provide Username and Password of MDM administrator as well as command to run on all gateways.

2: Main Path: {gwpath}

3: Script Output: {gwout} 

gw_stdout.json - main output file
gw_inventory.json - all domains -> all managed gateways
gw_mapping.json - responsive gateway -> managed domain
gw_failures.json - connectivity failures, CPRID version issues

[Performance]
Takes about 20 minutes to run 'uptime' on 300+ gateways'''
)

    parser.add_argument('-d', '--debug', action='store_true') # enable debugging in logs
    
    parser.add_argument('-h', '--help', action='help', default=argparse.SUPPRESS,
                help='')
    
    a = vars(parser.parse_args())
    
    parser.name = input("Username: ")
    parser.pw = input("Password: ")
    parser.domain = input("'all' Domains or IP of specific Domain: ")
    parser.command = input("Command to run on all gateways: ")
    parser.emailq = input("[yes or no] Email? : ")
    if parser.emailq != 'no': 
        parser.emailacc = input("Email To: ")
        parser.filename = input("Name of output file: ")
        parser.smtpserver = input("Name of smtp server: ")
    
    global username, password, targetdomain, command, emailacc, filename, smtpserver, emailq
    username = parser.name
    password = parser.pw 
    targetdomain = parser.domain
    command = parser.command
    emailq = parser.emailq
    if emailq != 'no': 
        emailacc = parser.emailacc
        filename = parser.filename.replace(' ', '_' )
        smtpserver = parser.smtpserver 
    
    print(f'''Monitor progress in separate session\n
# tail -F {gwpath}/log.log''')

    global debug
    if a['debug'] is True: 
        debug = 1
    else: 
        debug = 0 


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


# create bash scripts
def runcmd(cmd, script):
    
    script = f'{gwbin}/{script}'

    bash=f"""{shell} 
{cpprofile} 
{cmd} 
exit 0
"""

    if debug == 1:
        Log.debug(f'''[ contents ]\n{bash}\n 
[ script]\n{script}
[[ Does everything look right? ]]\n''')
        pause_debug()

    with open(script, 'w') as f: 
        f.write(bash)

    os.system(f"chmod +x {script}")
    
    try:
        response = subprocess.check_output(script, shell=True, text=True, timeout=60)
        if response is not None:
            cmdout = response
        else: 
            return
    except subprocess.TimeoutExpired as e:
        Log.error(traceback.print_exc())
        Log.error(f"[runcmd] : Error : {e}")

    if debug == 1: 
        Log.debug(f"[ runcmd ]\n{cmdout}\n\n")
        pause_debug()
    
    return cmdout

# make list of CMA IP Addresses
def domains():
    
    global domainlist
    
    if targetdomain == 'all': 
        dmcmd = "mdsstat | grep -i cma | awk '{print $6}' | grep -v 138.108.2.29"
        script = f'tmp_gw_bulk_domains_list.sh'
        domainlist = runcmd(dmcmd, script).split()
        if debug == 1:
            Log.debug(f"[ DOMAIN LIST ]\n{domainlist}\n")
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
                script = f'tmp_gateways_{count}_{domain}_tmp.sh'
                gwlist = runcmd(cmd, script).split()
                for i in gwlist: 
                    inventory[domain].append(i)
                
    except Exception as e: 
        Log.error(traceback.print_exc())
        Log.error(f"[gateways] : Error {e}\n")

    Log.info(f"[gateways] : Gateway List Complete")

# test connectivity
def testconn(ip, port, tmout): 

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(tmout)
    result = sock.connect_ex((ip,int(port)))
    return result

# create output 
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
cprid_util -server {gwip} -verbose rexec -rcmd bash -c "{command}"'''
                    script = f'tmp_bash_gw-{gwip}_tmp.sh'
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


def email(FN): 
    msg = EmailMessage()
    msg['Subject'] = f'{filename} gw_bulk'
    msg['From'] = "SCHMGMT01@enterprisenet.org"
    msg['To'] = emailacc
    
    cprid, failed = report()
    
    msg.set_content(f'''
No output or cprid failed
{cprid}

No connectivity to gateway
{failed}
'''
    )
    
    with open(FN, 'rb') as f: 
        file_data = f.read()
        
    msg.add_attachment(file_data, maintype='text', subtype='plain', filename=f'{filename}.tgz')
    
    with smtplib.SMTP(smtpserver) as server: 
        server.send_message(msg)
        server.quit()


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
    
    cmd = f'tar -czvf {gwout}/{filename}_gw_bulk.tgz {gwout}/*.csv {gwout}/*.json'        
    runcmd(cmd, 'tar_stdout.sh')
    


def report(): 

    cprid = {}
    failed = {}
    
    # reverse lookup of inventory for gateways with cprid issues 
    Log.info("\n\n[ No Output or CPRID issue ]\n\n")
    try:
        for fail,reason in failures.items():
            if 'NULL' in reason or 'Empty' in reason:
                for key,value in inventory.items():
                    if fail in value:
                        cprid[fail] = key
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
                        failed[fail] = key
                        Log.info(f"Gateway {fail} : Domain {key}")
    except Exception as e:
        Log.error(f"[ report ] : Error {e}\n")
        
    return cprid,failed



def cleanup():
    # remove undeleted tmp scripts and old output files
    os.system(f"rm {gwbin}/* {gwout}/*")


def main(): 
    
    # Help Menu and configuration
    args()
    
    # create direcotries
    mkdir() 
    
    # get domains list 
    domains()
    
    # get list of gateways from domains
    gateways()

    # send command and gather output
    output()
    
    # write output files 
    writefiles()
    
    # Email results
    if emailq != 'no':  
        email(f'{gwout}/{filename}_gw_bulk.tgz')


if __name__ == "__main__": 
    
    try:
        starttime = time.time()
        Log.info(f"Start Time: {starttime}")
        cleanup() 
        main()
    except Exception as e:
        Log.error(f"[main] : Error : {e}\n")
        Log.error(traceback.print_exc())
    finally:
        cleanup()
        endtime = time.time()
        totaltime = endtime - starttime
        Log.info(f"\n Total Run Time : {totaltime} seconds")
        end()
