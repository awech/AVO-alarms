#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys,os

doc="""Usage: {me} [options] -c command args..

{me}: A wrapper command to provide an advisory lock, without leaving stale lock files.

Options:
  -h, --help            show this help message and exit
  -f LOCK_FILE, --lock-file=LOCK_FILE
                        Path to the lock file. Default is provided based on the command path if omitted.
  -s, --status          Check to see if the file is locked, and if so, by which process. Exit status is 0
                        if unlocked, 1 if locked.

flock(2)'ed file is used to provide locking. This will not leave stale lock files around. 
Note that the existance of lock file does not mean that there is an outstanding lock; 
exclusive flock must be held by a process. 
So use '{me} --status -f /tmp/foo.lock' to see if the lock is held. 

The OS releases the lock upon process termination, so the lock file is released 
regardless of how the job terminated.

Invocations: 

* {me} -c long-running-scrit arg1 arg2
  will ensure only one long-running-scrit will run at a time.
  Default lock file, specific to the command, is used in the absence of -f option.

* Lockfile can be explicitely specified as:
  {me} -f /tmp/lrs-foo.lock -c long-running-scrit foo
  Two jobs using the same command could be run concurrently by using different lock files, like:
  {me} -f /tmp/lrs-bar.lock -c long-running-scrit bar

* Use --status (-s) option to check if a command or a file is locked:
  {me} -s -f /tmp/foo.lock
  {me} -s -c long-running-scrit 

Example: $ {me} -c sleep 3 & for x in {{0..6}}; do {me} -s -c sleep; sleep 1; done
  [1] 32567
  locked by 32567: /tmp/single.py_bin_sleep.flock
  locked by 32567: /tmp/single.py_bin_sleep.flock
  locked by 32567: /tmp/single.py_bin_sleep.flock
  [1]+  Done                    {me} sleep 5
  not locked: /tmp/single.py_bin_sleep.flock
  not locked: /tmp/single.py_bin_sleep.flock

""".format(me=os.path.basename(sys.argv[0]))

from datetime import datetime
from optparse import OptionParser
from fcntl import flock,LOCK_SH,LOCK_EX,LOCK_UN,LOCK_NB
from subprocess import Popen, PIPE

class CommandNotFound(Exception): pass

class Lock(object):
    """ a wrapper around flock(2) """

    def __init__(self, lock_file):
        self.lock_file=lock_file
        self.lock_fh=None

    def get_lock(self):
        """ lock my fh only, witout any book-keeping. returns True when lock is obtained. """

        self.lock_fh=os.open(self.lock_file, os.O_CREAT|os.O_RDWR) # read/write without truncate
        try:
            flock(self.lock_fh, LOCK_EX|LOCK_NB)
        except IOError, e:
            if e.args[0]==11: # Resource temporarily unavailable
                return False
            else:
                raise
        return True

    def lock(self):
        """ returns True if I got the lock, False otherwise.
        """

        return self.lock_pid()[0]

    def lock_pid(self):
        """ Returns <locked,pid> pair.
            If locked is true, I got the lock.
            Else, someone else is holding the lock, 
            in which case, pid is the owners pid or -1 for error.
        """

        if self.get_lock():
            self.write_pid()
            return True, None

        return False, self.read_pid()

    def write_pid(self):
        os.ftruncate(self.lock_fh, 0)
        os.write(self.lock_fh, '%d\n' % os.getpid())
        os.fsync(self.lock_fh)

    def read_pid(self):
        """ returns pid or -1 """

        content=os.read(self.lock_fh, 16) # just reading pid
        if not content:
            return -1

        try:
            return int(content.strip())
        except Exception, e:
            e.args+=(content, self.lock_file)
            raise

    def unlock(self):
        """ undo the lock. 
            this can be omitted since the OS will release the lock upon process termination.
        """
        flock(self.lock_fh, LOCK_UN)
        self.lock_fh.close()

def default_lock_file(cmd):
    """ generate a name that maps to the 'same invocation' that should be excluded.
    there is not way to be sure, so optimize this convenience feature for the 
    most common case. envisioned usage case is a custom script that does some job processing.
    Thus the resolved command executable (without regards to the args) should be used for the name space.
    """
    out,err=Popen(['which', cmd], stdout=PIPE, stderr=PIPE).communicate()
    cmd_path=out.strip()
    if not cmd_path:
        raise CommandNotFound('no such command:', cmd)
    return '/tmp/%s%s.flock' % (os.path.basename(sys.argv[0]), cmd_path.replace('/','_'))

#### cmd
def do_status(lock_file):
    """ check to see if there is a lock on the file.
        returns exit status: 0 for unlocked file, 1 for locked file.
    """

    lock=Lock(lock_file)
    gotit,pid=lock.lock_pid()
    if gotit:
        print 'not locked: %s' % (lock_file)
        return 0

    print 'locked by %d: %s' % (pid, lock_file)
    return 1

def wrap(lock_file, cmd_tokens):

    lock=Lock(lock_file)
    gotlock, pid=lock.lock_pid()
    if not gotlock:
        print >>sys.stderr, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), \
            'locked by ', pid, 'exiting:', ' '.join(cmd_tokens)
        sys.exit(1)
    else:
        os.execvp(cmd_tokens[0], cmd_tokens)

def main():
    """ parse opts and perform the requested operation.
    """
    # 
    # To keep optparse from being confused by the args to the wrapped command, 
    # the argv is split (into args_for_me and cmd_tokens) before being pased to optparse. 
    # Anything up to and including the first occurance of -c belongs to me (single).
    # The rest becomes the command line to be run.
    # 
    args=sys.argv[1:]
    from itertools import takewhile
    args_for_me=list(takewhile(lambda x: x!='-c', args))
    cmd_tokens=args[len(args_for_me):]
    if cmd_tokens:
        assert cmd_tokens.pop(0)=='-c'

    parser=OptionParser(add_help_option=False)
    parser.add_option("-h",
                      "--help",
                      action="store_true", # xx just want to make it not ask for value..
                      dest="help",
                      help="help")
    parser.add_option("-f", 
                      "--lock-file", 
                      dest="lock_file",
                      help="Path to the lock file. Default is provided based on the command path if omitted.")
    parser.add_option("-s",
                      "--status",
                      action="store_true",
                      dest="status",
                      help="Check to see if the file is locked, and if so, by which process. "
                      +"Exit status is 0 if unlocked, 1 if locked.")

    (opt, xargs) = parser.parse_args(args_for_me)

    if opt.help:
        print doc
        sys.exit(0)
    
    if not cmd_tokens:
        print doc
        sys.exit(1)
    
    try:
        lock_file=opt.lock_file or default_lock_file(cmd_tokens[0])
    except CommandNotFound, e:  # concise message for unresolved command
        print >>sys.stderr, ' '.join(e.args)
        sys.exit(1)

    if opt.status:
        status=do_status(lock_file)
    else:
        status=wrap(lock_file, cmd_tokens)

    sys.exit(status)

if __name__=='__main__':

    main()
