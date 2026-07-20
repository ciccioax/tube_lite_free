#!/usr/bin/env python3
import os, signal
from daemonize import Daemonize

PID = '/tmp/tubelite.pid'
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.py')

def main():
    os.execv('/usr/bin/python3', ['python3', SCRIPT])

if os.path.exists(PID):
    try:
        with open(PID) as f: old=int(f.read().strip())
        os.kill(old, signal.SIGTERM)
    except: pass

daemon = Daemonize(app='tubelite', pid=PID, action=main)
daemon.start()
print('TubeLite avviato. PID in', PID)
