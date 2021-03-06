# Licensed under the Apache License, Version 2.0 (the "License")
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# 
#     http://www.apache.org/licenses/LICENSE-2.0
# 
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import sys
import math
import MySQLdb
import h5py
import numpy as np
from contextlib import closing

from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings

from ocpuser.models import Project
from ocpuser.models import Dataset
from ocpuser.models import Token
from ocpuser.models import Channel
import annotation
from ocptype import IMAGE_CHANNELS, ANNOTATION_CHANNELS, ZSLICES, ISOTROPIC, READONLY_TRUE, READONLY_FALSE, PUBLIC_TRUE, NOT_PROPAGATED, UNDER_PROPAGATION, PROPAGATED, IMAGE, ANNOTATION, TIMESERIES, MYSQL, CASSANDRA, RIAK, OCP_servermap

# need imports to be conditional
try:
  from cassandra.cluster import Cluster
except:
   pass
try:
  import riak
except:
   pass

from ocpcaerror import OCPCAError
import logging
logger=logging.getLogger("ocp")


"""While this is not a true inheritance hierarchy from OCPCADataset->OPCPCAProject->OCPCAChannel
    modeling it as such makes it easier to call things on the channel.  It has dataset properties, etc."""

class OCPCADataset:
  """Configuration for a dataset"""

  def __init__ ( self, dataset_name ):
    """Construct a db configuration from the dataset parameters""" 
    
    try:
      self.ds = Dataset.objects.get(dataset_name = dataset_name)
    except ObjectDoesNotExist, e:
      logger.warning ( "Dataset {} does not exist. {}".format(dataset_name, e) )
      raise OCPCAError ( "Dataset {} does not exist".format(dataset_name) )

    self.resolutions = []
    self.cubedim = {}
    self.imagesz = {}
    self.offset = {}
    self.voxelres = {}
    self.scale = {}
    self.scalingoption = self.ds.scalingoption
    self.scalinglevels = self.ds.scalinglevels
    self.timerange = (self.ds.starttime, self.ds.endtime)
    # nearisotropic service for Stephan
    self.nearisoscaledown = {}
    self.neariso_voxelres = {}
    self.neariso_imagesz = {}
    self.neariso_offset = {}

    for i in range (self.ds.scalinglevels+1):
      """Populate the dictionaries"""

      # add this level to the resolutions
      self.resolutions.append( i )

      # set the image size
      #  the scaled down image rounded up to the nearest cube
      xpixels = ((self.ds.ximagesize-1)/2**i)+1
      ypixels = ((self.ds.yimagesize-1)/2**i)+1
      if self.ds.scalingoption == ZSLICES:
        zpixels = self.ds.zimagesize
      else:
        zpixels = ((self.ds.zimagesize-1)/2**i)+1
      self.imagesz[i] = [ xpixels, ypixels, zpixels ]

      # set the offset
      xoffseti = 0 if self.ds.xoffset==0 else ((self.ds.xoffset)/2**i)
      yoffseti = 0 if self.ds.yoffset==0 else ((self.ds.yoffset)/2**i)
      if self.ds.zoffset == 0:
        zoffseti = 0
      else:
        if self.ds.scalingoption == ZSLICES:
          zoffseti = self.ds.zoffset
        else:
         zoffseti = ((self.ds.zoffset)/2**i)

      self.offset[i] = [ xoffseti, yoffseti, zoffseti ]

      # set the voxelresolution
      xvoxelresi = self.ds.xvoxelres*float(2**i)
      yvoxelresi = self.ds.yvoxelres*float(2**i)
      zvoxelresi = self.ds.zvoxelres if self.ds.scalingoption == ZSLICES else self.ds.zvoxelres*float(2**i)

      self.voxelres[i] = [ xvoxelresi, yvoxelresi, zvoxelresi ]
      self.scale[i] = { 'xy':xvoxelresi/yvoxelresi , 'yz':zvoxelresi/xvoxelresi, 'xz':zvoxelresi/yvoxelresi }
      
      # choose the cubedim as a function of the zscale
      #self.cubedim[i] = [128, 128, 16]
      # this may need to be changed.  
      if self.ds.scalingoption == ZSLICES:
        #self.cubedim[i] = [512, 512, 16]
        self.cubedim[i] = [128, 128, 16]
        if float(self.ds.zvoxelres/self.ds.xvoxelres)/(2**i) >  0.5:
          self.cubedim[i] = [128, 128, 16]
        else: 
          self.cubedim[i] = [64, 64, 64]

        # Make an exception for bock11 data -- just an inconsistency in original ingest
        if self.ds.ximagesize == 135424 and i == 5:
          self.cubedim[i] = [128, 128, 16]
      else:
        # RB what should we use as a cubedim?
        self.cubedim[i] = [512, 512, 16]
      
      if self.scale[i]['xz'] < 1.0:
        scalepixels = 1/self.scale[i]['xz']
        if ((math.ceil(scalepixels)-scalepixels)/scalepixels) <= ((scalepixels-math.floor(scalepixels))/scalepixels):
          self.nearisoscaledown[i] = int(math.ceil(scalepixels))
        else:
          self.nearisoscaledown[i] = int(math.floor(scalepixels))
      else:
        self.nearisoscaledown[i] = int(1)
      
      self.neariso_imagesz[i] = [ xpixels, ypixels, zpixels/self.nearisoscaledown[i] ]
      self.neariso_voxelres[i] = [ xvoxelresi, yvoxelresi, zvoxelresi*self.nearisoscaledown[i] ]
      self.neariso_offset[i] = [ float(xoffseti), float(yoffseti), float(zoffseti)/self.nearisoscaledown[i] ]


  # Accessors
  def getDatasetName(self):
    return self.ds.dataset_name
  def getResolutions(self):
    return self.resolutions
  def getPublic(self):
    return self.ds.public
  def getImageSize(self):
    return self.imagesz
  def getOffset(self):
    return self.offset
  def getScale(self):
    return self.scale
  def getVoxelRes(self):
    return self.voxelres
  def getCubeDims(self):
    return self.cubedim
  def getTimeRange(self):
    return self.timerange
  def getDatasetDescription ( self ):
    return self.ds.dataset_description

  def checkCube (self, resolution, corner, dim, timeargs=[0,0]):
    """Return true if the specified range of values is inside the cube"""

    [xstart, ystart, zstart ] = corner
    [tstart, tend] = timeargs

    from operator import add
    [xend, yend, zend] = map(add, corner, dim) 

    if ( ( xstart >= 0 ) and ( xstart < xend) and ( xend <= self.imagesz[resolution][0]) and\
        ( ystart >= 0 ) and ( ystart < yend) and ( yend <= self.imagesz[resolution][1]) and\
        ( zstart >= 0 ) and ( zstart < zend) and ( zend <= self.imagesz[resolution][2]) and\
        ( tstart >= self.timerange[0]) and ((tstart < tend) or tstart==0 and tend==0) and (tend <= (self.timerange[1]+1))):
      return True
    else:
      return False

  def imageSize ( self, resolution ):
    """Return the image size"""
    return  [ self.imagesz [resolution], self.timerange ]


class OCPCAProject:

  def __init__(self, token_name ) :

    if isinstance(token_name, str) or isinstance(token_name, unicode):
      try:
        self.tk = Token.objects.get(token_name = token_name)
        self.pr = Project.objects.get(project_name = self.tk.project_id)
        self.datasetcfg = OCPCADataset(self.pr.dataset_id)
      except ObjectDoesNotExist, e:
        logger.warning ( "Token {} does not exist. {}".format(token_name, e) )
        raise OCPCAError ( "Token {} does not exist".format(token_name) )
    elif isinstance(token_name, Project):
      # Constructor for OCPCAProject from Project Name
      try:
        self.tk = None
        self.pr = token_name
        self.datasetcfg = OCPCADataset(self.pr.dataset_id)
      except ObjectDoesNotExist, e:
        logger.warning ( "Token {} does not exist. {}".format(token_name, e) )
        raise OCPCAError ( "Token {} does not exist".format(token_name) )

  # Accessors
  def getToken ( self ):
    return self.tk.token_name
  def getDBHost ( self ):
      return self.pr.host
  def getKVEngine ( self ):
    return self.pr.kvengine
  def getKVServer ( self ):
    return self.pr.kvserver
  def getDBName ( self ):
    return self.pr.project_name
  def getProjectName ( self ):
    return self.pr.project_name
  def getProjectDescription ( self ):
    return self.pr.project_description
  def getOCPVersion ( self ):
    return self.pr.ocp_version
  def getSchemaVersion ( self ):
    return self.pr.schema_version

  def projectChannels ( self, channel_list=None ):
    """Return a generator of Channel Objects"""
    if channel_list is None:
      chs = Channel.objects.filter(project_id=self.pr)
    else:
      chs = channel_list
    for ch in chs:
      yield OCPCAChannel(self, ch.channel_name)

  def getChannelObj ( self, channel_name='default' ):
    """Returns a object for that channel"""
    if channel_name == 'default':
      channel_name = Channel.objects.get(project_id=self.pr, default=True)
    return OCPCAChannel(self, channel_name)

  def getDBUser( self ):
    return settings.DATABASES['default']['USER']
  def getDBPasswd( self ):
    return settings.DATABASES['default']['PASSWORD']


class OCPCAChannel:

  def __init__(self, proj, channel_name = None):
    """Constructor for a channel. It is a project and then some."""
    try:
      self.pr = proj
      self.ch = Channel.objects.get(channel_name = channel_name, project=self.pr.getProjectName())
    except ObjectDoesNotExist, e:
      logger.warning ( "Channel {} does not exist. {}".format(channel_name, e) )
      raise OCPCAError ( "Channel {} does not exist".format(channel_name) )

  def getChannelModel ( self ):
    return Channel.objects.get(channel_name=self.ch.channel_name, project=self.pr.getProjectName())
  def getDataType ( self ):
    return self.ch.channel_datatype
  def getChannelName ( self ):
    return self.ch.channel_name
  def getChannelType ( self ):
    return self.ch.channel_type
  def getChannelDescription ( self ):
    return self.ch.channel_description
  def getExceptions ( self ):
    return self.ch.exceptions
  def getReadOnly (self):
    return self.ch.readonly
  def getResolution (self):
    return self.ch.resolution
  def getWindowRange (self):
    return [self.ch.startwindow,self.ch.endwindow]
  def getPropagate (self):
    return self.ch.propagate
  def isDefault (self):
    return self.ch.default 

  def getIdsTable (self):
    if self.pr.getOCPVersion() == '0.0':
      return "ids"
    else:
      return "{}_ids".format(self.ch.channel_name)

  def getTable (self, resolution):
    """Return the appropriate table for the specified resolution"""
    if self.pr.getOCPVersion() == '0.0':
      return "res{}".format(resolution)
    else:
      if self.pr.getKVEngine() == MYSQL:
        return "{}_res{}".format(self.ch.channel_name, resolution)
      elif self.pr.getKVEngine() == CASSANDRA:
        return "{}_{}".format(self.ch.channel_name, 'cuboids')

  def getNearIsoTable (self, resolution):
    """Return the appropriate table for the specified resolution"""
    if self.pr.getOCPVersion() == '0.0':
      return "res{}neariso".format(resolution)
    else:
      return "{}_res{}neariso".format(self.ch.channel_name, resolution)

  def getKVTable (self, resolution):
    """Return the appropriate KvPairs for the specified resolution"""
    if self.pr.getOCPVersion() == '0.0':
      return "kvpairs{}".format(resolution)
    else:
      return "{}_kvpairs{}".format(self.ch.channel_name, resolution)
  
  def getIdxTable (self, resolution):
    """Return the appropriate Index table for the specified resolution"""
    if self.pr.getOCPVersion() == '0.0':
      return "idx{}".format(resolution)
    else:
      if self.pr.getKVEngine() == MYSQL:
        return "{}_idx{}".format(self.ch.channel_name, resolution)
      elif self.pr.getKVEngine() == CASSANDRA:
        return "{}_{}".format(self.ch.channel_name, 'indexes')

  def getAnnoTable (self, anno_type):
    """Return the appropriate table for the specified type"""
    if self.pr.getOCPVersion() == '0.0':
      return "{}".format(annotation.anno_dbtables[anno_type])
    else:
      return "{}_{}".format(self.ch.channel_name, annotation.anno_dbtables[anno_type])

  def getExceptionsTable (self, resolution):
    """Return the appropiate exceptions table for the specified resolution"""
    if self.pr.getOCPVersion() == '0.0':
      return "exc{}".format(resolution)
    else:
      return "{}_exc{}".format(self.ch.channel_name, resolution)

  def setPropagate (self, value):
    if value in [NOT_PROPAGATED, PROPAGATED]:
      self.ch.propagate = value
      self.setReadOnly ( READONLY_FALSE )
      self.ch.save()
    elif value in [UNDER_PROPAGATION]:
      self.ch.propagate = value
      self.setReadOnly ( READONLY_TRUE )
      self.ch.save()
    else:
      logger.error ( "Wrong Propagate Value {} for Channel {}".format( value, self.ch.channel_name ) )
      raise OCPCAError ( "Wrong Propagate Value {} for Channel {}".format( value, self.ch.channel_name ) )
  
  def setReadOnly (self, value):
    if value in [READONLY_TRUE, READONLY_FALSE]:
      self.ch.readonly = value
      self.ch.save()
    else:
      logger.error ( "Wrong Readonly Value {} for Channel {}".format( value, self.channel_name ) )
      raise OCPCAError ( "Wrong Readonly Value {} for Channel {}".format( value, self.ch.channel_name ) )

  def isPropagated (self):
    if self.ch.propagate in [PROPAGATED]:
      return True
    else:
      return False

class OCPCAProjectsDB:
  """Database for the projects"""

  def __init__(self):
    """Create the database connection"""

    self.conn = MySQLdb.connect (host = settings.DATABASES['default']['HOST'], user = settings.DATABASES['default']['USER'], passwd = settings.DATABASES['default']['PASSWORD'], db = settings.DATABASES['default']['NAME']) 

  # for context lib closing
  def close (self):
    pass

  def newOCPCAProject ( self, project_name ):
    """Make the database for a project."""

    pr = Project.objects.get(project_name=project_name)

    if pr.kvengine == MYSQL:
      with closing(MySQLdb.connect (host = pr.host , user = settings.DATABASES['default']['USER'], passwd = settings.DATABASES['default']['PASSWORD'])) as conn:
        with closing(conn.cursor()) as cursor:

          try:
            # Make the database 
            sql = "CREATE DATABASE {}".format(pr.project_name)
         
            cursor.execute ( sql )
            conn.commit()
          except MySQLdb.Error, e:
            logger.error ("Failed to create database for new project {}: {}. sql={}".format(e.args[0], e.args[1], sql))
            raise OCPCAError ("Failed to create database for new project {}: {}. sql={}".format(e.args[0], e.args[1], sql))
    
    elif pr.kvengine == CASSANDRA:
      
      try:
        server_address = OCP_servermap[pr.kvserver]
        cluster = Cluster([server_address])
        session = cluster.connect()
        if server_address == 'localhost':  
          session.execute ("CREATE KEYSPACE {} WITH REPLICATION = {{ 'class' : 'SimpleStrategy', 'replication_factor' : 0 }}".format(pr.project_name), timeout=30)
        else:
          session.execute ("CREATE KEYSPACE {} WITH REPLICATION = {{ 'class' : 'SimpleStrategy', 'replication_factor' : 1 }}".format(pr.project_name), timeout=30)
      except Exception, e:
        pr.delete()
        logger.error("Failed to create namespace for new project {}".format(project_name))
        raise OCPCAError("Failed to create namespace for new project {}".format(project_name))
      finally:
        session.shutdown()


  def newOCPCAChannel ( self, project_name, channel_name ):
    """Make the tables for a channel."""

    pr = Project.objects.get(project_name=project_name)
    ch = Channel.objects.get(channel_name=channel_name, project_id=project_name)
    ds = Dataset.objects.get(dataset_name=pr.dataset_id)

    # Connect to the database

    if pr.kvengine == MYSQL:
      with closing (MySQLdb.connect(host = pr.host, user = settings.DATABASES['default']['USER'], passwd = settings.DATABASES['default']['PASSWORD'], db = pr.project_name)) as conn:
        with closing(conn.cursor()) as cursor:
          
          try:
            # tables specific to all other non time data
            if ch.channel_type not in [TIMESERIES]:
              for i in range(ds.scalinglevels+1): 
                cursor.execute ( "CREATE TABLE {}_res{} ( zindex BIGINT PRIMARY KEY, cube LONGBLOB )".format(ch.channel_name,i) )
            # tables specific to timeseries data
            elif ch.channel_type == TIMESERIES:
              for i in range(ds.scalinglevels+1): 
                cursor.execute ( "CREATE TABLE {}_res{} ( zindex BIGINT, timestamp INT, cube LONGBLOB, PRIMARY KEY(zindex,timestamp))".format(ch.channel_name,i) )
            else:
              raise OCPCAError("Channel type {} does not exist".format(ch.channel_type()))
            
            # tables specific to annotation projects
            if ch.channel_type == ANNOTATION: 
              cursor.execute("CREATE TABLE {}_ids ( id BIGINT PRIMARY KEY)".format(ch.channel_name))
              # And the RAMON objects
              cursor.execute ( "CREATE TABLE {}_annotations (annoid BIGINT PRIMARY KEY, type INT, confidence FLOAT, status INT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_seeds (annoid BIGINT PRIMARY KEY, parentid BIGINT, sourceid BIGINT, cube_location INT, positionx INT, positiony INT, positionz INT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_synapses (annoid BIGINT PRIMARY KEY, synapse_type INT, weight FLOAT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_segments (annoid BIGINT PRIMARY KEY, segmentclass INT, parentseed INT, neuron INT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_organelles (annoid BIGINT PRIMARY KEY, organelleclass INT, parentseed INT, centroidx INT, centroidy INT, centroidz INT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_nodes ( annoid BIGINT PRIMARY KEY, skeletonid BIGINT, nodetype INT, parentid BIGINT, locationx FLOAT, locationy FLOAT, locationz FLOAT, radius FLOAT )".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_skeletons (annoid BIGINT PRIMARY KEY, skeletontype INT, rootnode INT)".format(ch.channel_name))
              cursor.execute ( "CREATE TABLE {}_kvpairs ( annoid BIGINT, kv_key VARCHAR(255), kv_value VARCHAR(20000), PRIMARY KEY ( annoid, kv_key ))".format(ch.channel_name))
              for i in range(ds.scalinglevels+1):
                cursor.execute ( "CREATE TABLE {}_exc{} ( zindex BIGINT, id BIGINT, exlist LONGBLOB, PRIMARY KEY ( zindex, id))".format(ch.channel_name,i))
                cursor.execute ( "CREATE TABLE {}_idx{} ( annid BIGINT PRIMARY KEY, cube LONGBLOB )".format(ch.channel_name,i))
           
            # Commiting at the end
            conn.commit()
          except MySQLdb.Error, e:
            ch.delete()
            logging.error ("Failed to create tables for new project {}: {}.".format(e.args[0], e.args[1]))
            raise OCPCAError ("Failed to create tables for new project {}: {}.".format(e.args[0], e.args[1]))

    elif pr.kvengine == RIAK:
      #RBTODO figure out new schema for Riak
      rcli = riak.RiakClient(host=pr.kvserver, pb_port=8087, protocol='pbc')
      bucket = rcli.bucket_type("ocp{}".format(proj.getProjectType())).bucket(proj.getDBName())
      bucket.set_property('allow_mult',False)

    elif pr.kvengine == CASSANDRA:
      try:
        if ch.channel_type not in [TIMESERIES]:
          cluster = Cluster([pr.kvserver])
          session = cluster.connect(pr.project_name)
          session.execute ( "CREATE table {}_cuboids ( resolution int, zidx bigint, cuboid text, PRIMARY KEY ( resolution, zidx ) )".format(ch.channel_name), timeout=30)
        #session.execute( "CREATE table exceptions ( resolution int, zidx bigint, annoid bigint, exceptions text, PRIMARY KEY ( resolution, zidx, annoid ) )", timeout=30)
        #session.execute("CREATE table indexes ( resolution int, annoid bigint, cuboids text, PRIMARY KEY ( resolution, annoid ) )", timeout=30)
      except Exception, e:
        ch.delete()
        logging.error("Failed to create table for channel {}".format(channel_name))
        raise OCPCAError("Failed to create table for channel {}".format(channel_name))
      finally:
        session.shutdown()
      
    else:
      logging.error ("Unknown KV Engine requested: {}".format("RBTODO get name"))
      raise OCPCAError ("Unknown KV Engine requested: {}".format("RBTODO get name"))


  def deleteOCPCADB (self, project_name):

    pr = Project.objects.get(project_name = project_name)

    if pr.kvengine == MYSQL:
      with closing(MySQLdb.connect (host = pr.host, user = settings.DATABASES['default']['USER'], passwd = settings.DATABASES['default']['PASSWORD'])) as conn:
        with closing(conn.cursor()) as cursor:
        # delete the database
          sql = "DROP DATABASE {}".format(pr.project_name)

          try:
            cursor.execute(sql)
            conn.commit()
          except MySQLdb.Error, e:
            # Skipping the error if the database does not exist
            if e.args[0] == 1008:
              logger.warning("Database {} does not exist".format(pr.project_name))
              pass
            else:
              conn.rollback()
              logger.error ("Failed to drop project database {}: {}. sql={}".format(e.args[0], e.args[1], sql))
              raise OCPCAError ("Failed to drop project database {}: {}. sql={}".format(e.args[0], e.args[1], sql))


    elif pr.kvengine == CASSANDRA:
      try:
        cluster = Cluster( [pr.kvserver] )
        session = cluster.connect()
        session.execute ( "DROP KEYSPACE {}".format(pr.project_name), timeout=30 )
      except Exception, e:
        logger.warning("Keyspace {} does not exist".format(pr.project_name))
        pass
      finally:
        cluster.shutdown()

    elif pr.kvengine == RIAK:
      # connect to Riak
      rcli = riak.RiakClient(host=proj.kvserver, pb_port=8087, protocol='pbc')
      bucket = rcli.bucket_type("ocp{}".format(proj.getProjectType())).bucket(proj.getDBName())

      key_list = rcli.get_keys(bucket)

      for k in key_list:
        bucket.delete(k)


  def deleteOCPCAChannel (self, proj, channel_name):
    """Delete the tables for this channel"""

    pr = OCPCAProject(proj)
    ch = OCPCAChannel(pr, channel_name)
    table_list = []

    if ch.getChannelType() in ANNOTATION_CHANNELS:
      table_list.append(ch.getIdsTable())
      for key in annotation.anno_dbtables.keys():
        table_list.append(ch.getAnnoTable(key))

    for i in pr.datasetcfg.getResolutions():
      table_list.append(ch.getTable(i))
      if ch.getChannelType() in ANNOTATION_CHANNELS:
        table_list = table_list + [ch.getIdxTable(i), ch.getExceptionsTable(i)]

    print table_list
    if pr.getKVEngine() == MYSQL:
      try:
        conn = MySQLdb.connect (host = pr.getDBHost(), user = settings.DATABASES['default']['USER'], passwd = settings.DATABASES['default']['PASSWORD'], db = pr.getProjectName() ) 
        # delete the tables for this channel
        sql = "DROP TABLES IF EXISTS {}".format(','.join(table_list))
      
        with closing(conn.cursor()) as cursor:
          cursor.execute (sql)
          conn.commit()
      except MySQLdb.Error, e:
        # Skipping the error if the table does not exist
        if e.args[0] == 1051:
          pass
        if e.args[0] == 1049:
          pass
        else:
          conn.rollback()
          logger.error ("Failed to drop channel tables {}: {}. sql={}".format(e.args[0], e.args[1], sql))
          raise OCPCAError ("Failed to drop channel tables {}: {}. sql={}".format(e.args[0], e.args[1], sql))
      
    elif pr.getKVEngine() == CASSANDRA:
      # KL TODO
      pass
    
    elif pr.getKVEngine() == RIAK:
      # KL TODO
      pass

  def loadDatasetConfig ( self, dataset ):
    """Query the database for the dataset information and build a db configuration"""
    return OCPCADataset (dataset)

  def loadToken ( self, token ):
    """Query django configuration for a token to bind to a project"""
    return OCPCAProject (token)

  def getPublic ( self ):
    """ Return a list of public tokens """

    tkns = Token.objects.filter(public = PUBLIC_TRUE)
    return [t.token_name for t in tkns]
