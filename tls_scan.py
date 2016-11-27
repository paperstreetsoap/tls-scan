#!/usr/bin/env python
# tls-scan - Automated TLS/SSL Server Tests for Multiple Hosts
# https://github.com/ArtiomL/tls-scan
# Artiom Lichtenstein
# v1.0.2, 27/11/2016

import argparse
import atexit
import email.mime.text as email
import json
import lib.cfg as cfg
import lib.log as log
import lib.reapi as reapi
import os
import re
import smtplib
import sys
import time

__author__ = 'Artiom Lichtenstein'
__license__ = 'MIT'
__version__ = '1.0.1'

# Config file
strCFile = 'tls_scan.json'

# Log prefix
log.strLogID = '[-v%s-161127-] %s - ' % (__version__, os.path.basename(sys.argv[0]))

# SSL Labs REST API
objSLA = reapi.clsSLA()

# Exit codes
class clsExCodes(object):
	def __init__(self):
		self.cfile = 10
		self.nosrv = 8

objExCodes = clsExCodes()

# Final grades list
lstGrades = []

# Mail From:
strMFrom = 'tls-scan v%s' % __version__

def funResult(amStatus):
	# Add grades to list or print assessment JSON
	global lstGrades
	if isinstance(amStatus, list):
		for i in amStatus:
			log.funLog(1, i)
		lstGrades.extend(amStatus)
	elif isinstance(amStatus, dict):
		print json.dumps(amStatus, indent = 4)


def funScan(lstHosts, boolCache):
	# Initiate the scan
	for strHost in lstHosts:
		if not boolCache and not objSLA.funAnalyze(strHost):
			# If cached reports aren't allowed (default) - but a new assessment has failed to start
			continue
		funResult(objSLA.funOpStatus(strHost))


def funConScan(lstHosts, boolCache):
	# Concurrent scan
	# Split the hosts list into groups of the concurrency size
	lstMatrix = [lstHosts[i:i + objSLA.intConc] for i in range(0, len(lstHosts), objSLA.intConc)]
	# Initiate the scan
	for lstGroup in lstMatrix:
		# New assessment
		if not boolCache:
			for strHost in lstGroup:
				objSLA.funAnalyze(strHost)
				time.sleep(objSLA.intCool)
		# Check status
		intReady = 0
		while intReady < len(lstGroup):
			# Completed assessments counter
			intReady = 0
			time.sleep(objSLA.intPoll)
			for i, strHost in enumerate(lstGroup):
				if strHost.endswith('#'):
					intReady += 1
					continue
				# Non-blocking operation status
				amStatus = objSLA.funOpStatus(strHost, True)
				if amStatus:
					# Mark host as completed
					lstGroup[i] += '#'
					intReady += 1
					funResult(amStatus)


def funArgParser():
	objArgParser = argparse.ArgumentParser(
		description = 'Automated TLS/SSL Server Tests for Multiple Hosts',
		epilog = 'https://github.com/ArtiomL/tls-scan')
	objArgParser.add_argument('-c', help ='deliver cached assessment reports if available', action = 'store_true', dest = 'cache')
	objArgParser.add_argument('-f', help ='config file location', dest = 'cfile')
	objArgParser.add_argument('-j', help ='return assessment JSONs (default: grades only), disables -m', action = 'store_true', dest = 'json')
	objArgParser.add_argument('-l', help ='set log level (default: 0)', choices = [0, 1, 2, 3], type = int, dest = 'log')
	objArgParser.add_argument('-m', help ='send report by mail', action = 'store_true', dest = 'mail')
	objArgParser.add_argument('-s', help ='number of simultaneous assessments (default: 1)', choices = [2, 3, 4, 5], type = int, dest = 'conc')
	objArgParser.add_argument('-v', action ='version', version = '%(prog)s v' + __version__)
	objArgParser.add_argument('HOST', help = 'list of hosts to scan (overrides config file)', nargs = '*')
	return objArgParser.parse_args()


def main():
	global objSLA, strCFile, lstGrades, strMHead
	objArgs = funArgParser()

	# If run interactively, stdout is used for log messages (unless -j is set)
	if sys.stdout.isatty() and not objArgs.json:
		log.strLogMethod = 'stdout'

	# Set log level
	if objArgs.log:
		log.intLogLevel = objArgs.log

	# Full assessment JSON argument
	objSLA.boolJSON = objArgs.json

	# Config file location
	if objArgs.cfile:
		strCFile = objArgs.cfile

	# Concurrency
	if objArgs.conc:
		objSLA.intConc = objArgs.conc

	# Read config file
	diCfg = cfg.funReadCfg(strCFile)
	try:
		lstHosts = diCfg['hosts']
	except Exception as e:
		log.funLog(1, 'Invalid config file: %s' % strCFile, 'err')
		log.funLog(2, repr(e), 'err')
		sys.exit(objExCodes.cfile)


	# List of hosts to scan (override)
	if objArgs.HOST:
		lstHosts = objArgs.HOST

	# Hosts list cleanup (remove invalid domains)
	lstHClean = [strHost for strHost in lstHosts if objSLA.funValid(strHost)]
	if len(lstHosts) > len(lstHClean):
		log.funLog(1, 'Ignoring invalid hostname(s): %s' % ', '.join(list(set(lstHosts) - set(lstHClean))), 'err')
	lstHosts = lstHClean

	log.funLog(1, 'Scanning %s host(s)... [Cache: %s]' % (str(len(lstHosts)), bool(objArgs.cache)))

	# Check SSL Labs availability
	if not objSLA.funInfo():
		log.funLog(1, 'SSL Labs unavailable or maximum concurrent assessments exceeded.', 'err')
		sys.exit(objExCodes.nosrv)


	# Scan
	if objSLA.intConc > 1:
		# Concurrency
		funConScan(lstHosts, objArgs.cache)
	else:
		funScan(lstHosts, objArgs.cache)

	# Sort the grades in reverse and add line breaks
	strReport = '\r\n'.join(sorted(lstGrades, reverse = True))

	# Format 
	objMIME = email.MIMEText(strReport)

	# Mail the report
	if objArgs.mail and not objArgs.json:
		try:
			objMIME['From'] = diCfg['from']
			objMIME['To'] = diCfg['to']
			objMIME['Subject'] = 'TLS/SSL Scan Report'
			objMail = smtplib.SMTP(diCfg['server'])
			objMail.ehlo()
			objMail.starttls()
			objMail.login(diCfg['user'], diCfg['pass'].decode('base64'))
			lstTo = re.split(r',|;', diCfg['to'].replace(' ', ''))
			#strMHead += '<%s>\nTo: %s\nSubject: TLS/SSL Scan Report\n\nTotal Hosts Submitted: %s\n' % (diCfg['from'], ','.join(lstTo), str(len(lstHosts)))
			objMail.sendmail(diCfg['from'], lstTo, objMIME.as_string())
			objMail.quit()
		except Exception as e:
			log.funLog(2, repr(e), 'err')
	else:
		print strReport


def funBadExit(type, value, traceback):
	log.funLog(1, 'Unhandled Exception: %s, %s, %s' % (type, value, traceback))

sys.excepthook = funBadExit


@atexit.register
def funExit():
	log.funLog(1, 'Exiting...')


if __name__ == '__main__':
	main()
