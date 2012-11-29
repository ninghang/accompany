import time, os, sys
from subprocess import Popen, PIPE
from config import ros_config

class ROS(object):
    _envVars = {}
    
    def __init__(self, *args, **kwargs):
        ROS.configureROS(packageName='rospy')
        import rospy
        self._rospy = rospy
        self._topicTypes = {}
        self._subscribers = {}
        self.initROS()
        
    def __del__(self):
        for sub in self._subscribers.values():
            sub.unregister()
        
    def initROS(self, name='rosHelper'):
        if not self._rospy.core.is_initialized():
            self._rospy.init_node('rosHelper', anonymous=True, disable_signals=True)
        
    def getSingleMessage(self, topic, dataType=None, retryOnFailure=1, timeout=None):
        
        try:
            if dataType == None:
                if not self._topicTypes.has_key(topic):
                    self._topicTypes[topic] = self.getMessageType(topic)
                    
                dataType = self._topicTypes[topic]

            if not self._subscribers.has_key(topic):
                self._subscribers[topic] = RosSubscriber(topic, dataType)

            subscriber = self._subscribers[topic]
            while not subscriber.hasNewMessage:
                if timeout != None:
                    if timeout < 0:
                        break
                    else:
                        timeout -= 0.01
                time.sleep(0.01)                
    
            return subscriber.lastMessage
        except:
            if retryOnFailure > 0:
                return self.getSingleMessage(topic, dataType, retryOnFailure - 1, timeout)
            else:
                return None
    
    def getTopics(self, baseFilter=''):
        topics = self._rospy.get_published_topics(baseFilter)
        return topics

    def getMessageType(self, topic):
        controller_name = topic[0: topic.rfind('/')]
        controller_msgType = None
        
        topics = self.getTopics(controller_name)
        for pubTopic in topics:
            if pubTopic[0] == topic:
                controller_msgType = pubTopic[1]
                break
        
        if controller_msgType == None:
            raise Exception('Could not determine ROS messageType for topic: %s' % (topic))
        
        manifest = controller_msgType.split('/')[0]
        cls = controller_msgType.split('/')[1]
        
        try:
            import roslib
            roslib.load_manifest(manifest)
            
            ns = __import__(manifest + '.msg', globals(), locals(), [cls], -1)
            msgCls = getattr(ns, cls)
            return msgCls
        except Exception as e:
            raise Exception('Error occured while loading message class: %s' % (e))
        
    @staticmethod
    def parseRosBash(version=None):
        version = version or ros_config['version']
        if not ROS._envVars.has_key(version):
            #executes the bash script and exports env vars
            bashScript = '/opt/ros/%s/setup.bash' % version
            env = {}
            if os.path.exists(bashScript):
                rosEnv = ROS.parseBashEnviron('source ' + bashScript)
                allEnv = ROS.parseBashEnviron()
        
                #find all the variables that ros added/changed
                for key, value in rosEnv.items():
                    if not allEnv.has_key(key):
                        env[key] = value
                    elif allEnv[key] != value:
                        #We really only want the bit that ros added
                        env[key] = value.replace(allEnv[key], '').strip(':')
        
                #Add in any overrides from the config file
                env.update(ros_config['envVars'])

            ROS._envVars[version] = env

        return ROS._envVars[version]

    @staticmethod
    def parseBashEnviron(preCommand=''):
        command = ['bash', '-c', ('%s; env' % preCommand).strip('; ')]
        pipe = Popen(command, stdout=PIPE)
        data = pipe.communicate()[0]
        env = dict((line.split("=", 1) for line in data.splitlines()))
        return env

    @staticmethod
    def configureROS(version=None, packagePath=None, packageName=None, rosMaster=None, overlayPath=None):
        """Any values not provided will be read from ros_config in config.py"""
        version = version or ros_config['version']

        for k, v in ROS.parseRosBash(version).items():
            if k == 'PYTHONPATH' and sys.path.count(v) == 0:
                sys.path.append(v)
            elif not os.environ.has_key(k):
                os.environ[k] = v
            elif k.endswith('PATH'):
                os.environ[k] = ':'.join((v, os.environ[k]))

        overlayPath = overlayPath or ros_config['overlayPath']

        #if 'ROS_MASTER_URI' not in os.environ.keys():
        if rosMaster != None:
            os.environ['ROS_MASTER_URI'] = rosMaster

        path = '/opt/ros/%(version)s/ros' % { 'version': version}
        if 'ROS_ROOT' not in os.environ.keys() or os.environ['ROS_ROOT'] != path:
            os.environ['ROS_ROOT'] = path

        path = '%(root)s/bin' % { 'root': os.environ['ROS_ROOT']}
        if os.environ['PATH'].find(path) == -1:
            os.environ['PATH'] = ':'.join((path, os.environ['PATH']))

        path = '/opt/ros/%(version)s/stacks' % { 'version': version}
        if 'ROS_PACKAGE_PATH' not in os.environ.keys():
            os.environ['ROS_PACKAGE_PATH'] = path
        elif os.environ['ROS_PACKAGE_PATH'].find(path) == -1:
            os.environ['ROS_PACKAGE_PATH'] = ':'.join((path, os.environ['ROS_PACKAGE_PATH']))  

        path = os.path.expanduser(overlayPath)
        if os.environ['ROS_PACKAGE_PATH'].find(path) == -1:
            os.environ['ROS_PACKAGE_PATH'] = ':'.join((path, os.environ['ROS_PACKAGE_PATH']))

        path = packagePath or os.path.dirname(os.path.realpath(__file__)) + '/ROS_Packages'
        if os.environ['ROS_PACKAGE_PATH'].find(path) == -1:
            os.environ['ROS_PACKAGE_PATH'] = ':'.join((path, os.environ['ROS_PACKAGE_PATH']))

        path = '%(root)s/core/roslib/src' % { 'root': os.environ['ROS_ROOT']}
        if sys.path.count(path) == 0:
            sys.path.append(path)

        if packageName != None:
            import roslib
            roslib.load_manifest(packageName)

class RosSubscriber(object):
    
    def __init__(self, topic, dataType, idleTime=15):
        ROS.configureROS(packageName='rospy')
        import rospy
        self._rospy = rospy
        self._lastAccess = time.time()
        self._subscriber = None
        self._topic = topic
        self._dataType = dataType
        self._newMessage = False
        self._idleTimeout = idleTime

    @property
    def hasNewMessage(self):
        self._touch()
        return self._newMessage
    
    @property
    def lastMessage(self):
        self._touch()
        self._newMessage = False
        return self._data
    
    def _touch(self):
        self._lastAccess = time.time()
        if self._subscriber == None:
            self._subscriber = self._rospy.Subscriber(self._topic, self._dataType, self._callback)
    
    def unregister(self):
        if self._subscriber != None:
            self._subscriber.unregister()
            self._subscriber = None
       
    def _callback(self, msg):
        self._data = msg
        self._newMessage = True
        if time.time() - self._lastAccess > self._idleTimeout:
            self.unregister()

if __name__ == '__main__':
    r = ROS()
    er = 0
    start = time.clock()
    num = 1000
    while(er < num):
        r.getSingleMessage('/head_controller/state')
        er +=1

    print 'iterationTime = ' + str((time.clock() - start) / num)