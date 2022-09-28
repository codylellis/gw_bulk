[ Description ] 

Execute commands across all gateways on MDM.  

Only runs on MDM. 


[ Instructions ] 

1. Provide Username and Password of MDM administrator as well as command to run on all gateways. 


2. /var/log/gw_bulk - main output directory 


3. /var/log/gw_bulk/output/

gw_stdout.json - main output file 

gw_inventory.json - all domains -> all managed gateways 

gw_mapping.json - responsive gateway -> managed domain

gw_failures.json - connectivity failures, CPRID version issues 

gw_successful.json - output exists from responsive gateway


[ Performance ] 

Takes about 20 minutes to run 'uptime' on 300+ gateways


[ Troubleshooting ] 

(NULL BUF) = CPRID version issue or general CPRID error (sk174346)
