# -*- coding: utf-8 -*-
# by Sebastian Brand (538838.com)
# 
# Version 1.0

import os # replace with subprocess?
import copy
import shutil
import threading

# Defines settings and files in a folder
class tv_folder:
    def __init__(self, name, path):
        self.name = name
        self._path = ""
        self._tty = 1
        self._configfile = "folder.conf"
        self.images = []
        self.videos = []
        self._acceptedImageFormats = ['.jpg', '.jpeg', '.ppm', '.tif', '.tiff', '.xwd', '.bmp', '.png']
        self._acceptedVideoFormats = ['.mpg', '.mp4', '.mkv']
        self._defaultSettings = {"start": "", "stop": "", "mode": "image", "imagetime": 30, "imageiterations": 1, "videosound":0}        
        self.settings = copy.copy(self._defaultSettings)
        self._temporaryFolder = ""
        self._thread = None
        self._event = None
        
        #sysenc = sys.getfilesystemencoding()
        #sysPath = path.encode(sysenc)
        if os.path.isdir(path):
            self._path = path
            
# Copies media from remote location to temporary folder
# Returns error string
    def prepare(self,tmpfolder):
        self._temporaryFolder = tmpfolder
        if os.path.exists(self._temporaryFolder) == True:
            return "Folder already exists: " + self.name
        os.mkdir(self._temporaryFolder)
        if self.settings["mode"] == "image" or self.settings["mode"] == "both":
            for i in self.images:
                shutil.copyfile(os.path.join(self._path,i),os.path.join(self._temporaryFolder,i))
        if self.settings["mode"] == "video" or self.settings["mode"] == "both":
            for v in self.videos:
                shutil.copyfile(os.path.join(self._path,v),os.path.join(self._temporaryFolder,v))
        return None
    
    def cleanup(self,tmpfolder=None):
        if tmpfolder == None:
            tmpfolder = self._temporaryFolder
            self._temporaryFolder = ""
        
        if os.path.isdir(tmpfolder) == False or tmpfolder == "":
            return "Cannot remove temporary folder: " + self.name
        for f in os.listdir(tmpfolder):
            os.remove(os.path.join(tmpfolder,f))
        os.rmdir(tmpfolder)
        return None
        
    def start(self,startTV=False):
        self._event = threading.Event()
        self._thread = threading.Thread(target=self._show, args = ())
        self._thread.start()
        return None
    
    def stop(self):
        self._event.set()
        #wait for thread to die
        self._thread.join()
        self._thread = None
        self._event = None
        return None
        
# Show Images and (todo videos) until notified by tv_daemon
    def _show(self):
        #Omxplayer for videos
        #as to not crash due to changed data
        event = self._event # same object
        temporaryFolder = copy.copy(self._temporaryFolder) # copy
        settings = copy.copy(self.settings) # copy
        images = copy.copy(self.images) # copy
        videos = copy.copy(self.videos) # copy       
        imageString = ""
        for i in images:
	    iesc = i.replace(" ", "\\ ") 
            imageString = imageString + os.path.join(temporaryFolder,iesc) + " "   

        while event.isSet() == False:
            if len(images) == 1:
                command = "fbi -T " + str(self._tty) + " --noverbose -a "
		command2 = "fbi -T 2" + " --noverbose -a "
            else:
                command = "fbi -T " + str(self._tty) + " --noverbose -a -t " + str(settings["imagetime"]) + " "
		command2 = "fbi -T 2" + " --noverbose -a -t " + str(settings["imagetime"]) + " "
            os.system(command + imageString)
	    #Uglyfix
	    os.system(command2 + imageString)
            event.wait()
            os.system("killall fbi > /dev/tty" + str(self._tty))
	    os.system("killall fbi > /dev/tty2")
# Updates settings and media set if necessary.
# Returns updated(True/False),error text [None for success]
    def update(self):
        updated = False
        settings,status = self._readConf()                
        if settings == None:
            return None,status
	if not settings == self.settings:
            updated = True
            self.settings = settings        

        files = [ f for f in os.listdir(self._path) if os.path.isfile(os.path.join(self._path,f)) ]
        images = []
        videos = []
        for f in files:
            if f[0] != '#' and f != self._configfile:
                name, ext = os.path.splitext(f)
                if ext in self._acceptedImageFormats:
                    images.append(f)
                elif ext in self._acceptedVideoFormats:
                    videos.append(f)
        
        if set(images) != set(self.images):
            self.images = images
            if self.settings["mode"] == "image" or self.settings["mode"] == "both":
                updated = True
        if set(videos) != set(self.videos):
            self.videos = videos
            if self.settings["mode"] == "video" or self.settings["mode"] == "both":
                updated = True
        
        if self.settings["mode"] == "both":
            if len(self.videos) == 0:
                self.settings["mode"] = "image"        
            elif len(self.images) == 0:
                self.settings["mode"] = "video"
        
        if self.settings["mode"] == "image":
            if len(self.images) == 0:
                return None,"No images found: " + self.name
        elif self.settings["mode"] == "video":
            if len(self.videos) == 0:
                return None,"No images found: " + self.name
            
        return updated,None

# Reads config from config file. 
# Returns settings, error text [None for success]
#
    def _readConf(self):
        # Check if path and configfile exists
        if os.path.isdir(self._path) == False:
            return None, self.name + ": Cannot open folder"
        if os.path.exists(os.path.join(self._path,self._configfile)) == False:
            return None,self.name + ": Cannot find the file " + self._configfile
        
        inFile = open(os.path.join(self._path,self._configfile),'r')
        settings = copy.copy(self._defaultSettings)
        
        lineIndex = 0;
        for line in inFile:
            lineIndex += 1
            line = line.strip()
            if line != "" and line[0] != '#':
                line = line.lower()
                split = line.split('=')
                if len(split) != 2:
                    return None,"Missing parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                option = split[0].strip()
                value = split[1].strip()
                
                ## Settings
                if option == "start":
                    settings["start"] = value
                elif option == "stop":
                    settings["stop"] = value
                elif option == "mode":
                    if value == "image" or value == "video" or value == "both":
                        settings["mode"] = value
                    else:
                        return None,"Invalid parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                elif option == "imagetime":
                    try:
                        t = int(value)
                    except ValueError:
                        return None,"Missing parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                    if t < 0 or t > 10000:
                        return None,"Too big/small parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                    settings["imagetime"] = t
                elif option == "imageiterations":
                    try:
                        i = int(value)
                    except ValueError:
                        return None,"Invalid parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                    if t < 0 or t > 10000:
                        return None,"Too big/small parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
                    settings["imageiterations"] = i
                elif option == "videosound":
                    if value == "1" or value == "0":
                        settings["videosound"] = value
                    else:
                        return None,"Invalid parameter: " + os.path.join(self._path,self._configfile) + ":" + str(lineIndex)
        inFile.close()
        return settings,None

if __name__ == '__main__':
    # Kept for debugging
