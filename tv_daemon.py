# -*- coding: utf-8 -*-
# by Sebastian Brand (538838.com)
# Version 1.0
#
# started (forked) by /etc/rc.local

import os #replace with subprocess?
import tv_folder
import time
import parsedatetime
import re as regexp
from datetime import datetime,timedelta
from time import mktime 
from logging.handlers import RotatingFileHandler
import logging
import shutil
import RPi.GPIO as gpio
import threading

class tv_daemon:
    
    # Initiates all necessary stuff
    def __init__(self):
        os.chdir("/root/tvscript_v1.0")
        self._configfile = "tv.conf"
        self._mount = "/mnt/tv/"
        self._temporary = "/var/tmp/tv/"
        self._logfile = "/var/log/tv.log"
        self._pinIn = 13        
        self._pinOut = 15
        self._cecSleep = 20
        self._mountSleep = 30
	self._clearSleep = 10
        self._settings = {"on": True, "source": True, "off": True, "type": "samba", "source": "", "user": "", "pass": "", "time": 30, "default": True, "noDefaultTvCtrl": True, "maxTime": 60}        
        self._logMaxBytes = 10000000        
        self._logbackupCount = 5        
        
        self._folders = []
        self._tvFolders = []
        self._active = None
        self._default = None
        self._semaphore = threading.Semaphore()              
        
    def init(self):        
        # Add logger
        self._logger = logging.getLogger()
        self._logger.setLevel(logging.INFO)
        handler = RotatingFileHandler(self._logfile, maxBytes=self._logMaxBytes,backupCount=self._logbackupCount)
        handler.setFormatter(logging.Formatter("(%(levelname)s) %(asctime)s: %(message)s"))        
        self._logger.addHandler(handler)        
        self._logger.info("== Starting ==")
        # Create parsedatetime object, and nexttime variable
        self._pdtcal = parsedatetime.Calendar()
        self._nextTime = self._parse("2038-01-01")[0] 
        self._lastUpdate = self._parse("1970-01-01")[0]
        
        err = None        
        err = self._readConf()
        if err != None:
            self._logger.error(err)            
        
        # Mount
        if self._settings["type"] == "samba":
            c = "mount -t cifs -o username=" + self._settings["user"] + ",password=" + self._settings["pass"] + ",noserverino" + " " + self._settings["source"] + " " + self._mount
            os.system(c)
            while not os.path.ismount(self._mount):
                self._logger.error("Could not mount, retries")
                c = "mount -t cifs -o username=" + self._settings["user"] + ",password=" + self._settings["pass"] + ",noserverino" + " " + self._settings["source"] + " " + self._mount
                os.system(c)
                time.sleep(self._mountSleep)
        else:
            self._logger.error("Unknown mount_type")
                
        # Empty old temporary folder
        if os.path.exists(self._temporary):
            shutil.rmtree(self._temporary)
        os.mkdir(self._temporary)              
                
        # Start TV and set source
        if self._settings["on"] == True:
            os.system("echo \"on 0\" | /usr/bin/cec-client -s -d 1")
            if self._settings["source"] == True:
                time.sleep(self._cecSleep)
        if self._settings["source"] == True:
            os.system("echo \"as 0\" | /usr/bin/cec-client -s -d 1")
         
        # Clear screen (must be before gpio??)
        os.system("printf '\033[2J\033[1;1H' > /dev/tty1")
        os.system("setterm -cursor off > /dev/tty1")        
        
        time.sleep(30) # Might be needed to make trigger funtion correctly?
        # Set shutdown pin trigger and add delay to reset
        gpio.setmode(gpio.BOARD)
        gpio.setwarnings(False)
        #Delay
        gpio.setup(self._pinOut,gpio.OUT)
        gpio.output(self._pinOut, 0)
        #Shutdown pin
        gpio.setup(self._pinIn, gpio.IN,pull_up_down=gpio.PUD_UP)
        gpio.add_event_detect(self._pinIn, gpio.FALLING, callback=self.stop, bouncetime=200)
        
        self._logger.info("Successfully started")

    def stop(self,pin):        
        if gpio.input(pin) == 0:
            self._logger.info("Stopping script")
            self._semaphore.acquire()
            if self._active != None:            
                self._active.stop()
                err = self._active.cleanup()
                self._logger.error(err)
            os.system("umount " + self._mount)
            if self._settings["off"] == True:
                os.system("echo \"standby 0\" | /usr/bin/cec-client -s -d 1")
            self._logger.info("Shutting down pi")
            os.system("shutdown -h 0")
        
    def run(self):
	while True:
            self._semaphore.acquire()
            err = self._update()
            self._semaphore.release()
            if err != None:
                self._logger.error(err)
            time.sleep(self._settings["time"])

    def _update(self):
        updated = False
	activeRemoved = False
        updatedActive = False
        folders = [ f for f in os.listdir(self._mount) if os.path.isdir(os.path.join(self._mount,f)) and f[0] != '#' ]
        #if folders == []:
        #    return "No folders found"
            
        # Check for new folders on disk
        if set(folders) != set(self._folders):
            updated = True
            removed = [f for f in self._folders if f not in folders]
            new = [f for f in folders if f not in self._folders]
            self._folders = folders
            
            # Remove tv_folders
            for t in self._tvFolders:
                if t.name in removed:
                    # If active removed
                    if t == self._active:
                        self._active.stop()
                        self._active.cleanup()
                        self._active = None
			activeRemoved = True
                    self._tvFolders.remove(t)
                
            # Append new tv_folders
            for n in new:
                self._tvFolders.append(tv_folder.tv_folder(n,os.path.join(self._mount,n)))
        # Check for changes within folders
        for t in self._tvFolders:
            u,e = t.update()
            if e != None:
                return e
            if u == True:
                updated = True
                # Active changed?
                if t == self._active:
                    updatedActive = True
                    
        # If updated, or next timer: check which to run
        now = self._parse("now")[0]
        dt = now - self._lastUpdate
        dtmin = dt.days * 24 * 60 + dt.seconds/60
        if updated == True or now >= self._nextTime or dtmin >= self._settings["maxTime"]:
            self._lastUpdate = now            
            lastStart = self._parse("1970-01-01")[0]
            active = None
            nextTime = self._parse("2038-01-01")[0]
            default = None
            #Check all tv_folders
            for t in self._tvFolders:
                if t.settings["start"] == "": # Default
                    if default != None: # Multiple defaults
                        return "Missing start time in too many folders"
                    default = t
                else: # Standard
                    tStart,tStop = self._parse(t.settings["start"],t.settings["stop"])
                    if tStop == None:
                        return "Could not parse time: " + t.name
                    
                    # Latest started event (and active...)
                    if tStart <= now and tStart > lastStart and tStop >= now: 
                        lastStart = tStart
                        active = t
                        if tStop < nextTime: # Happends next
                            nextTime = tStop
                    # Next event?
                    if tStart > now and tStart < nextTime:
                        nextTime = tStart
            self._nextTime = nextTime
	    
            # If no active and default enabled: set default av active
            if active == None and self._settings["default"] == True:
                active = default
            
            # Change folder if change in active
            if self._active != active or activeRemoved == True:
                # If new active exists: prepare new
                if active != None:
                    tmpFolder = os.path.join(self._temporary,active.name) 
                    err = active.prepare(tmpFolder)
                    if err != None:
                        return err
                # If old active exists: stop old
                if self._active != None:
                    self._active.stop()
                # If new active exists: start new
                if active != None:
                    active.start()
                # If old active exists: cleanup
                if self._active != None:
                    err = self._active.cleanup()
                    if err != None:
                        return err
                        
                # Check if old active == None and tv_on, tv_source is set. Then talk with tv.        
                if self._active == None and self._settings["noDefaultTvCtrl"] == True and activeRemoved == False:
                    # Start TV and set source
		    #Uglyfix start hdmi
        	    os.system("/opt/vc/bin/tvservice -p")
		    time.sleep(self._cecSleep)
                    if self._settings["on"] == True:
                        os.system("echo \"on 0\" | /usr/bin/cec-client -s -d 1")
                        if self._settings["source"] == True:
                            time.sleep(self._cecSleep)
                    if self._settings["source"] == True:
                        os.system("echo \"as 0\" | /usr/bin/cec-client -s -d 1")
                # Check if new active == None and tv_off is set. Then talk with tv.
                if (active == None or activeRemoved == True) and self._settings["noDefaultTvCtrl"] == True:
                    if self._settings["off"] == True:
                        os.system("echo \"standby 0\" | /usr/bin/cec-client -s -d 1")
		    else:
			# Clear screen
			#time.sleep(self._clearSleep)
        		os.system("printf '\033[2J\033[1;1H' > /dev/tty1")
			#Uglyfix stop hdmi
        		os.system("/opt/vc/bin/tvservice -o")
                   
	    	# Update active
            	self._active = active
 
            # Active same as before, and changed
            elif self._active != None and updatedActive == True:
                # New and old folder names
                tmpFolder = os.path.join(self._temporary,active.name + "_2")
                oldTmpFolder = os.path.join(self._temporary,active.name)
                if os.path.isdir(tmpFolder) == True: # Assume no trash folders
                    tmp = tmpFolder
                    tmpFolder = oldTmpFolder
                    oldTmpFolder = tmp
                # Prepare new
                err = self._active.prepare(tmpFolder)
                if err != None:
                    return err
                # Restart
                self._active.stop()
                self._active.start()
                # Remove old teporary folder                
                err = self._active.cleanup(oldTmpFolder)
            # Write to log
            if not self._active == None:
                self._logger.info("Active folder: " + self._active.name)
            else:
                self._logger.info("Active folder: None")
            self._logger.info("Next event: " + str(nextTime))
        return None
             
    def _parse(self,startTime,stopTime=None):
        if stopTime == None:
            time_struct, status = self._pdtcal.parse(startTime)
            if status == 0: # Could not parse
            	return None,None
            time = datetime.fromtimestamp(mktime(time_struct))
            return time,None
        else:
            now = self._parse("now")[0]
            start = self._parse("this " + startTime)[0]
            stop = self._parse("this " + stopTime)[0]
            if start == None or stop == None: # Could not parse
                return None,None
            if stop > now:
                if start > stop: 
                    start = self._parse("last " + startTime)[0]
                    if start == None: # Could not parse
                        return None,None
                    #Handles special case with time only and pre midnight to pos midnight time
                    if start > stop:  
                        hhmm = regexp.match("2[0-3]:[0-5][0-9]|[0-1][0-9]:[0-5][0-9]",startTime)
                        if not hhmm == None:
                            start = start - timedelta(days=1)
            else:
                stop = self._parse("next " + stopTime)[0]
                if stop == None: # Could not parse
                    return None,None
                #Handles special case with time only and 
                if stop < now: # Still  
                    hhmm = regexp.match("2[0-3]:[0-5][0-9]|[0-1][0-9]:[0-5][0-9]",startTime)
                    if not hhmm == None:
                        stop = stop + timedelta(days=1)
                if start < now:
                    start = self._parse("next " + startTime)[0]
                    if start == None: # Could not parse
                        return None,None
                    #Handles special case with time only
                    if start < now: # still  
                        hhmm = regexp.match("2[0-3]:[0-5][0-9]|[0-1][0-9]:[0-5][0-9]",startTime)
                        if not hhmm == None:
                            start = start + timedelta(days=1)
        return start,stop
                
    
    def _readConf(self):
        # Check if path and configfile exists
        if os.path.exists(self._configfile) == False:
            return "Cannot find the file " + self._configfile
        
        inFile = open(self._configfile,'r')
        
        lineIndex = 0;
        for line in inFile:
            lineIndex += 1
            line = line.strip()
            if line != "" and line[0] != '#':
                
                split = line.split('=')
                if len(split) != 2:
                    return "Missing parameter: " + self._configfile + ":" + str(lineIndex)
                option = split[0].strip().lower()
                value = split[1].strip().lower()
                ## Settings
                if option == "onoff_tv_on":
                    if value == "0":
                        self._settings["on"] = False
                elif option == "onoff_tv_source":
                    if value == "0":
                        self._settings["source"] = False
                elif option == "onoff_tv_off":
                    if value == "0":
                        self._settings["off"] = False
                elif option == "mount_type":
                    if value != "samba":
                        return None,"Unknown mount type: " + self._configfile + ":" + str(lineIndex)
                    self._settings["type"] = value
                elif option == "mount_source":
                    self._settings["source"] = value
                elif option == "mount_username":
                    self._settings["user"] = split[1].strip()
                elif option == "mount_password":
                    self._settings["pass"] = split[1].strip()
                elif option == "show_update_time":
                    try:
                        t = int(value)
                    except ValueError:
                        return "Invalid parameter: " + self._configfile + ":" + str(lineIndex)
                    self._settings["time"] = t
                elif option == "show_max_update_time":
                    try:
                        t = int(value)
                    except ValueError:
                        return "Invalid parameter: " + self._configfile + ":" + str(lineIndex)
                    self._settings["maxTime"] = t 
                elif option == "show_default":
                    if value == "0":
                        self._settings["default"] = False
                elif option == "onoff_at_noDefault":
                    if value == "1":
                        self._settings["noDefaultTvCtrl"] = True
        inFile.close()        
        return None
         
if __name__ == '__main__':
    daemon = tv_daemon()
    daemon.init()
    daemon.run()
