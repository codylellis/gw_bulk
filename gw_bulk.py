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

# filepaths
global gwpath, gwbin, gwout
gwpath = os.path.dirname(os.path.abspath(__file__))
gwbin = f'{gwpath}/scripts'
gwout = f'{gwpath}/output'

# Logging 
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


class bulk: 
    def __init__(self): 
        self.mapping = {}
        self.gmapping = {}
        self.failures = {}
        self.inventory = {}
        self.stdout = {}
        self.domainlist = {}
        self.setup()
        self.targets()
        self.results()
        if self.emailq != 'no':  
            self.email(f'{gwout}/{self.filename}_gw_bulk.tgz')

    def setup(self): 
        self.args()
        self.mkdir()
    
    def targets(self): 
        self.domains()
        self.gateways()
    
    def results(self): 
        self.output()
        

    def args(self): 
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
MDM or SMS 

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
        
        self.username = parser.name
        self.password = parser.pw 
        self.targetdomain = parser.domain
        self.command = parser.command
        self.emailq = parser.emailq
        if self.emailq != 'no': 
            self.emailacc = parser.emailacc
            self.filename = parser.filename.replace(' ', '_' )
            self.smtpserver = parser.smtpserver 
        
        print(f'''Monitor progress in separate session\n
# tail -F {gwpath}/log.log''')

        global debug
        if a['debug'] is True: 
            debug = 1
        else: 
            debug = 0 


    # make log directory / clear old log files
    def mkdir(self):

        if os.path.isdir(gwpath) and os.path.isdir(gwbin) and os.path.isdir(gwout):
            Log.info(f'[Make Directories]... Exists!\n')
        else:
            Log.info(f'[Make Directories]... Does not exist\n')
            os.system(f'mkdir -v {gwpath} {gwbin} {gwout}')
            
    # create bash scripts
    def runcmd(self, cmd, script):
        
        shell = '#!/bin/bash'
        cpprofile = '''source /etc/profile.d/CP.sh
source /etc/profile.d/vsenv.sh
source $MDSDIR/scripts/MDSprofile.sh
source $MDS_SYSTEM/shared/mds_environment_utils.sh
source $MDS_SYSTEM/shared/sh_utilities.sh
'''
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
            self.pause_debug()

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
            Log.debug(f"[runcmd]\n{cmdout}\n\n")
            self.pause_debug()
        
        return cmdout
    
    # make list of CMA IP Addresses
    def domains(self):
        
        if self.targetdomain == 'all': 
            cmd = "mdsstat | grep -i cma | awk '{print $6}' | grep -v 138.108.2.29"
            self.domainlist = self.runcmd(cmd, 'tmp_gw_bulk_domains_list.sh').split()
            Log.info(f"[DOMAIN LIST]\n{self.domainlist}\n")
        else: 
            self.domainlist = [self.targetdomain]

    # generate list of gateways per CMA
    def gateways(self): 

        try:
            for domain in self.domainlist: 
                self.inventory[domain] = []
                Log.info(f"[gateways] : queryDB_util : {domain}\n")
                cmdlist =[
    f'''mdsenv {domain}
    (echo {domain};  echo {self.username}; echo {self.password}; echo "-t network_objects -s class='cluster_member'|type='gateway_ckp'|type='cluster_member' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' 
    ''',
    f'''mdsenv {domain}
    (echo {domain};  echo {self.username}; echo {self.password}; echo "-t network_objects -s class='gateway_ckp'&location='internal' -a -pf"; echo "-q") | queryDB_util | grep -E "^\s\s\s\sipaddr" | grep -v ipaddr6 | sed 's/    ipaddr: //g' | grep -v 'ipaddr_from_mac:' 
    ''' ]       
                count = 0
                for cmd in cmdlist: 
                    count += 1
                    gwlist = self.runcmd(cmd, f'tmp_gateways_{count}_{domain}_tmp.sh').split()
                    for i in gwlist: 
                        self.inventory[domain].append(i)
                    
        except Exception as e: 
            Log.error(traceback.print_exc())
            Log.error(f"[gateways] : Error {e}\n")

        Log.info(f"[gateways] : Gateway List Complete")    

    # create output 
    def output(self):
        count = 0
        failcount = 0
        errorcount = 0
        # test connectivity
        def testconn(ip, port, tmout): 
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(tmout)
            result = s.connect_ex((ip,int(port)))
            return result
        
        try:
            for domain in self.inventory.keys():
                for gwip in self.inventory[domain]:
                    if testconn(gwip, 18208, 5) != 0:
                        failcount += 1
                        Log.info(f"[testconn] : Check connectivity : {gwip}:18208 : Count {failcount}\n")
                        self.failures[gwip] = f"No connectivity on port 18208, Count {failcount}"
                    else:
                        count += 1
                        Log.info(f"[output] : {self.command} : {domain} | {gwip} : Count {count}\n")
                        # segfault (null buff) from os causes subprocess to fail
                        # and causes the entire script to exit, try/except does not work
                        # requires 'exit 0' at end of bash script
                        cmd = f'''mdsenv {domain}
cprid_util -server {gwip} -verbose rexec -rcmd bash -c "{self.command}"'''
                        result = self.runcmd(cmd, f'tmp_bash_gw-{gwip}_tmp.sh')
                        
                        if len(result) == 0:
                            errorcount += 1
                            Log.info(f"[output] : Output Empty : {gwip} : Count {errorcount}\n")
                            self.failures[gwip] = f"Empty Output {errorcount}"
                        elif 'NULL' in result:
                            errorcount += 1
                            Log.info(f"[output] : (NULL BUF) : {gwip} : Count {errorcount}\n")
                            self.failures[gwip] = f"CPRID Error : (NULL BUF) : Count {errorcount}"
                        else:
                            self.stdout[gwip] = result.strip()
        
        except Exception as e:
            Log.error(traceback.print_exc())
            Log.error(f"[output] : Error : {e}\n")
            
        # creating mapping of gateway to domain for later use
        try:
            for gw in self.stdout.keys(): 
                for key,value in self.inventory.items(): 
                    if gw in value: 
                        self.mapping[gw] = [key] 
        except Exception as e:
            Log.error(f"Error {e}\n")
        

    def writefiles(self):
            
        jfiles = {'inventory.json' : self.inventory,
                 'mapping.json' : self.mapping, 
                 'failures.json' : self.failures,
                 'stdout.json' : self.stdout} 
        
        for name,jout in jfiles.items(): 
            with open(f'{gwout}/{name}', 'w') as f:
                f.write(json.dumps(jout, indent=4, sort_keys=False))
        
        # make csv of stdout information 
        fcsv = f'{gwout}/gw_stdout.csv'
        with open(fcsv, 'w') as f:
            w = csv.writer(f)
            w.writerows(self.stdout.items())
        
        cmd = f'tar -czvf {gwout}/{self.filename}_gw_bulk.tgz {gwout}/*.csv {gwout}/*.json'        
        self.runcmd(cmd, 'tar_stdout.sh')


    def report(self): 

        self.cprid = {}
        self.failed = {}
        
        # reverse lookup of inventory for gateways with cprid issues 
        try:
            for fail,reason in self.failures.items():
                if 'NULL' in reason or 'Empty' in reason:
                    for key,value in self.inventory.items():
                        if fail in value:
                            self.cprid[fail] = key
                elif 'connectivity' in reason:
                    for key,value in self.inventory.items(): 
                        if fail in value:
                            self.failed[fail] = key
                            Log.info(f"Gateway {fail} : Domain {key}")
                            
            Log.info("\n\n[ Failed to connect to Gateway. ]\n\n")
            Log.info(self.failed)
            
            Log.info("\n\n[ No Output or CPRID issue ]\n\n")
            Log.info(self.cprid)
            
        except Exception as e:
            Log.error(f"[ report ] : Error {e}\n")


    def email(self, FN): 
        self.report()
        
        msg = EmailMessage()
        msg['Subject'] = f'{self.filename} gw_bulk'
        msg['From'] = "checkpointmgmt@checkpoint.com"
        msg['To'] = self.emailacc
        
        msg.set_content(f'''
    No output or cprid failed
    {self.cprid}

    No connectivity to gateway
    {self.failed}
    '''
        )
        
        with open(FN, 'rb') as f: 
            file_data = f.read()
            
        msg.add_attachment(file_data, maintype='text', subtype='plain', filename=f'{self.filename}.tgz')
        
        with smtplib.SMTP(self.smtpserver) as server: 
            server.send_message(msg)
            server.quit()

    def pause_debug(self):
        input("[PAUSE_DEBUG] Press any key to continue...\n\n") 


# script exit 
def end(): 
    sys.exit(0)
        
# remove scripts with usernames and passwords
def cleanup():
    os.system(f"rm {gwbin}/*.sh")


def main(): 
    
    start = bulk()


if __name__ == "__main__": 
    
    try:
        cleanup()
        starttime = time.time()
        Log.info(f"Start Time: {starttime}")
        main()
    except Exception as e:
        Log.error(f"[main] : Error : {e}\n")
        Log.error(traceback.print_exc())
    finally:
        endtime = time.time()
        totaltime = endtime - starttime
        Log.info(f"\n Total Run Time : {totaltime} seconds")
        cleanup()
        end()