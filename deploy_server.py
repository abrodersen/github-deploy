#!/usr/bin/python
"""
Github auto deploy server

When push to github, post request fired from github server.

This script should be compatable with python2.4 (centos 5.x)
"""
try:
    import json
except ImportError:
    import simplejson as json
import urlparse
import sys
import os
import time
import logging
import logging.handlers

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from subprocess import call

from threading import Lock

logger = logging.getLogger('github_deploy')
logger.setLevel(logging.INFO)


def log(message):
    logtime = time.strftime("%Y-%m-%d %H:%M:%S")
    message = "[%s] %s" % (logtime, message)

    logger.info(message)
    if GitDeploy.verbose:
        print message

def check_pid(pid):        
    """ Check For the existence of a unix pid. """
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    else:
        return True

class GitDeploy(BaseHTTPRequestHandler):
    CONFIG_FILEPATH = None
    config = None
    verbose = False
    lock = Lock()

    @classmethod
    def __init_config(cls):
        if not cls.CONFIG_FILEPATH:
            cls.CONFIG_FILEPATH = os.path.dirname(os.path.realpath(__file__))\
                + "/config.json"

        try:
            configString = open(cls.CONFIG_FILEPATH).read()
        except:
            sys.exit('Could not load ' + cls.CONFIG_FILEPATH + ' file')

        try:
            cls.config = json.loads(configString)
        except:
            sys.exit(cls.CONFIG_FILEPATH + ' file is not valid json')

        if 'log' in cls.config:
            handler = logging.handlers.RotatingFileHandler(cls.config['log'],
                    maxBytes=10 * 1024 * 1024, backupCount=5)
            logger.addHandler(handler)

        if 'allow_hosts' not in cls.config:
            # Add default github servers
            cls.config['allow_hosts'] = ["207.97.227.253", "50.57.128.197",
                    "108.171.174.178", "50.57.231.61"]

        for repository in cls.config['repositories']:
            if not os.path.isdir(repository['path']):
                sys.exit('Directory ' + repository['path'] + ' not found')

            if not os.path.isdir(repository['path'] + '/.git'):
                sys.exit('Directory %s is not a Git repository' %
                    repository['path'])

    @classmethod
    def get_config(cls):
        if cls.config is None:
            cls.__init_config()

        return cls.config

    def do_POST(self):
        """
        The post handler
        """

        if not self.check_ip():
            log("Invalid ip address (%s)" % (self.client_address[0]))
            return

        repos = self.parse_repository()
        if len(repos) > 0:
            self.lock.acquire()

            for repo in repos:
                self.pull(repo)
                if 'command' in repo:
                    self.exec_command(repo['command'])

            self.lock.release()

    def check_ip(self):
        """
        Check client ip address is valid github server
        """
        remote_addr = self.client_address[0]
        return remote_addr in self.get_config()['allow_hosts']

    def parse_repository(self):
        """
        Parse input data and check config's repository
        Return valid deploy url, path, branch dictionary list
        """
        length = int(self.headers.getheader('content-length'))
        body = self.rfile.read(length)
        post = urlparse.parse_qs(body)

        config = self.get_config()

        repos = []
        for itemString in post['payload']:
            item = json.loads(itemString)

            url = item['repository']['url']
            branch = item['ref'].split('/')[2]

            for repository in config['repositories']:
                if repository['url'] == url and repository['branch'] == branch:
                    data = {'url': url,
                        'path': repository['path'],
                        'branch': branch,
                        'before': item['before'],
                        'after': item['after']}

                    if 'command' in repository:
                        data['command'] = repository['command']

                    repos.append(data)
                    break

        return repos

    def respond(self):
        """
        Respond to github server
        """
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

    def pull(self, repo):
        """
        Execute pull command
        """

        user = self.get_config()['user']

        ret = call(["cd %s && sudo -u %s git pull origin %s" % (repo['path'],
            user, repo['branch'])], shell=True)

        result = 'Failed'
        if ret == 0:
            result = 'Success'

        message = "[{result}] {url} ({branch}) to {path}. {before} to {after}"\
            .format(result=result, url=repo['url'], branch=repo['branch'],
            path=repo['path'], before=repo['before'],
            after=repo['after'])
        log(message)

    def exec_command(self, command):
        user = self.get_config()['user']
        log("Execute command (%s)" % command)
        call(["sudo -u %s %s" % (user, command)])


if __name__ == '__main__':
    # check if root
    if os.geteuid() != 0:
        print >> sys.stderr, "You aren't root. Goodbye."
        sys.exit()

    try:
        server = None
        is_daemon = False
        pid_file = "/var/run/github-deploy.pid"

        for arg in sys.argv:
            if arg == '-v':
                GitDeploy.verbose = True
                print "started"

            if arg.find('--config=') == 0:
                GitDeploy.CONFIG_FILEPATH = arg.replace("--config=", "")
            
            if arg.find('--pidfile=') == 0:
                pid_file = arg.replace("--pidfile=", "")

            if arg == '-d':
                is_daemon = True

        if is_daemon:
            if os.path.isfile(pid_file):
                # check pid running
                f = open(pid_file, 'r')
                pid = f.read()
                f.close()
                if pid and check_pid(pid):
                    # running
                    print >> sys.stderr, "Already running"
                    sys.exit()
                else:
                    os.path.unlink(pid_file)

            pid = os.fork()
            if(pid != 0):
                sys.exit()
            os.setsid()

            f = open(pid_file, 'w+')
            f.write("%d" % os.getpid())
            f.close()

        server = HTTPServer(('', GitDeploy.get_config()['port']), GitDeploy)
        log("Server started...")
        server.serve_forever()

    except (KeyboardInterrupt, SystemExit) as e:
        if e:
            print >> sys.stderr, e

        if server is not None:
            server.socket.close()

# vim: expandtab:ts=4:sw=4:ai:si
