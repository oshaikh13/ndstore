# Licensed under the Apache License, Version 2.0 (the "License");
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

import MySQLdb
import h5py
import numpy as np
import math
from contextlib import closing

# need imports to be conditional
try:
  from cassandra.cluster import Cluster
except:
   pass
try:
  import riak
except:
   pass

import ocpcaprivate
from ocpcaerror import OCPCAError

import logging
logger=logging.getLogger("ocp")

# dbtype enumerations
IMAGES_8bit = 1
ANNOTATIONS = 2
CHANNELS_16bit = 3
CHANNELS_8bit = 4
PROBMAP_32bit = 5
BITMASK = 6
ANNOTATIONS_64bit = 7 
IMAGES_16bit = 8 
RGB_32bit = 9
RGB_64bit = 10

class OCPCAProject:
  """Project specific for cutout and annotation data"""

  # Constructor 
  def __init__(self, token, dbname, dbhost, dbtype, dataset, dataurl, readonly, exceptions, resolution, kvserver, kvengine ):
    """Initialize the OCPCA Project"""
    
    self._token = dbname
    self._dbname = dbname
    self._dbhost = dbhost
    self._dbtype = dbtype
    self._dataset = dataset
    self._dataurl = dataurl
    self._readonly = readonly
    self._exceptions = exceptions
    self._resolution = resolution
    self._kvserver = kvserver
    # for cassandra
    #self._kvserver = '172.23.253.63'
    self._kvengine = kvengine

    # Could add these to configuration.  Probably remove res as tablebase instead
    self._ids_tbl = "ids"

  # Accessors
  def getDBHost ( self ):
    return self._dbhost
  def getDBType ( self ):
    return self._dbtype
  def getDBName ( self ):
    return self._dbname
  def getDataset ( self ):
    return self._dataset
  def getDataURL ( self ):
    return self._dataurl
  def getIDsTbl ( self ):
    return self._ids_tbl
  def getExceptions ( self ):
    return self._exceptions
  def getDBType ( self ):
    return self._dbtype
  def getReadOnly ( self ):
    return self._readonly
  def getResolution ( self ):
    return self._resolution
  # RBTODO need to make the KVEngine a project attribute
  # PYTODO create a project attribute that selects KVEngine
  def getKVEngine ( self ):
    return self._kvengine


  # RBTODO need to make the KVSErver a project attribute
  # PYTODO create a project attribute that selects KVServer
  def getKVServer ( self ):
    return self._kvserver

  # accessors for RB to fix
  def getDBUser( self ):
    return ocpcaprivate.dbuser
  def getDBPasswd( self ):
    return ocpcaprivate.dbpasswd

  def getTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)

  def getIsotropicTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)+"iso"

  def getNearIsoTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)+"neariso"
  
  def getIdxTable ( self, resolution ):
    """Return the appropriate Index table for the specified resolution"""
    return "idx"+str(resolution)

class OCPCADataset:
  """Configuration for a dataset"""

  def __init__ ( self, ximagesz, yimagesz, startslice, endslice, zoomlevels, zscale, startwindow, endwindow ):
    """Construct a db configuration from the dataset parameters""" 

    self.slicerange = [ startslice, endslice ]
    self.windowrange = [ startwindow, endwindow ]

    # istropic slice range is a function of resolution
    self.isoslicerange = {} 
    self.nearisoscaledown = {}

    self.resolutions = []
    self.cubedim = {}
    self.imagesz = {}
    self.zscale = {}

    for i in range (zoomlevels+1):
      """Populate the dictionaries"""

      # add this level to the resolutions
      self.resolutions.append( i )

      # set the zscale factor
      self.zscale[i] = float(zscale)/(2**i);

      # choose the cubedim as a function of the zscale
      #  this may need to be changed.  
      if self.zscale[i] >  0.5:
        self.cubedim[i] = [128, 128, 16]
      else: 
        self.cubedim[i] = [64, 64, 64]

      # Make an exception for bock11 data -- just an inconsistency in original ingest
      if ximagesz == 135424 and i == 5:
        self.cubedim[i] = [128, 128, 16]

      # set the image size
      #  the scaled down image rounded up to the nearest cube
      xpixels=((ximagesz-1)/2**i)+1
      ypixels=((yimagesz-1)/2**i)+1
# RBRM -- don't round up to cubes.  Just pixels.
#      ximgsz = (((xpixels-1)/self.cubedim[i][0])+1)*self.cubedim[i][0]
#      yimgsz = (((ypixels-1)/self.cubedim[i][1])+1)*self.cubedim[i][1]
      self.imagesz[i] = [ xpixels, ypixels ]

      # set the isotropic image size when well defined
      if self.zscale[i] < 1.0:
        self.isoslicerange[i] = [ startslice, startslice + int(math.floor((endslice-startslice+1)*self.zscale[i])) ]

        # find the neareat to isotropic value
        scalepixels = 1/self.zscale[i]
        if ((math.ceil(scalepixels)-scalepixels)/scalepixels) <= ((scalepixels-math.floor(scalepixels))/scalepixels):
          self.nearisoscaledown[i] = int(math.ceil(scalepixels))
        else:
          self.nearisoscaledown[i] = int(math.floor(scalepixels))

      else:
        self.isoslicerange[i] = self.slicerange
        self.nearisoscaledown[i] = int(1)

  #
  #  Check that the specified arguments are legal
  #
  def checkCube ( self, resolution, xstart, xend, ystart, yend, zstart, zend ):
    """Return true if the specified range of values is inside the cube"""

    [xmax, ymax] = self.imagesz [ resolution ]

    if (( xstart >= 0 ) and ( xstart < xend) and ( xend <= self.imagesz[resolution][0]) and\
        ( ystart >= 0 ) and ( ystart < yend) and ( yend <= self.imagesz[resolution][1]) and\
        ( zstart >= self.slicerange[0] ) and ( zstart < zend) and ( zend <= (self.slicerange[1]+1))):
      return True
    else:
      return False

#
  #  Return the image size
  #
  def imageSize ( self, resolution ):
    return  [ self.imagesz [resolution], self.slicerange ]


class OCPCAProjectsDB:
  """Database for the annotation and cutout projects"""

  def __init__(self):
    """Create the database connection"""

    self.conn = MySQLdb.connect (host = ocpcaprivate.dbhost, user = ocpcaprivate.dbuser, passwd = ocpcaprivate.dbpasswd, db = ocpcaprivate.db ) 


  # for context lib closing
  def close (self):
    self.conn.close()

  #
  # Load the ocpca databse information based on the token
  #
  def loadProject ( self, token ):
    """Load the annotation database information based on the token"""

    # Lookup the information for the database project based on the token
    sql = "SELECT token, openid, host, project, datatype, dataset, dataurl, readonly, exceptions, resolution , kvserver, kvengine from %s where token = \'%s\'" % (ocpcaprivate.projects, token)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
        # get the project information 
        row= cursor.fetchone()
      except MySQLdb.Error, e:
        logger.error ("Could not query ocpca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Could not query ocpca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    # if the project is not found.  error
    if ( row == None ):
      logger.warning ( "Project token %s not found." % ( token ))
      raise OCPCAError ( "Project token %s not found." % ( token ))

    [token, openid, host, project, dbtype, dataset, dataurl, readonly, exceptions, resolution, kvserver, kvengine ] = row

    # Create a project object
    proj = OCPCAProject ( token, project, host, dbtype, dataset, dataurl, readonly, exceptions, resolution, kvserver, kvengine ) 
    proj.datasetcfg = self.loadDatasetConfig ( dataset )

    return proj

  #
  # Create a new dataset
  #
  def newDataset ( self, dsname, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale, startwindow, endwindow ):
    """Create a new ocpca dataset"""

    sql = "INSERT INTO {0} (dataset, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale, startwindow, endwindow) VALUES (\'{1}\',\'{2}\',\'{3}\',\'{4}\',{5},\'{6}\',\'{7}\', \'{8}\',\'{9}\')".format (\
       ocpcaprivate.datasets, dsname, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale, startwindow, endwindow )

    logger.info ( "Creating new dataset. Name %s. SQL=%s" % ( dsname, sql ))

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor = self.conn.cursor()
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        logger.error ("Could not query ocpca datsets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Could not query ocpca datsets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

      self.conn.commit()


  #
  # Create a new project (annotation or data)
  #
  def newOCPCAProj ( self, token, openid, dbhost, project, dbtype, dataset, dataurl, readonly, exceptions, nocreate, resolution, public, kvserver, kvengine ):
    """Create a new ocpca project"""

    datasetcfg = self.loadDatasetConfig ( dataset )

    sql = "INSERT INTO {0} (token, openid, host, project, datatype, dataset, dataurl, readonly, exceptions, resolution, public, kvserver, kvengine) VALUES (\'{1}\',\'{2}\',\'{3}\',\'{4}\',{5},\'{6}\',\'{7}\',\'{8}\',\'{9}\',\'{10}\',\'{11}\',\'{12}',\'{13}')".format (\
       ocpcaprivate.projects, token, openid, dbhost, project, dbtype, dataset, dataurl, int(readonly), int(exceptions), resolution, int(public), kvserver, kvengine )

    logger.info ( "Creating new project. Host %s. Project %s. SQL=%s" % ( dbhost, project, sql ))

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        logger.error ("Could not query ocpca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Could not query ocpca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

      self.conn.commit()

    proj = self.loadProject ( token )

    # Exception block around database creation
    try:

      # Make the database unless specified
      if not nocreate: 

        with closing(self.conn.cursor()) as cursor:
          try:
            # Make the database and associated ocpca tables
            sql = "CREATE DATABASE %s" % project
         
            cursor.execute ( sql )
            self.conn.commit()
          except MySQLdb.Error, e:
            logger.error ("Failed to create database for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
            raise OCPCAError ("Failed to create database for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))


        # Connect to the new database

        newconn = MySQLdb.connect (host = dbhost, user = ocpcaprivate.dbuser, passwd = ocpcaprivate.dbpasswd, db = project )
        newcursor = newconn.cursor()

        try:

          if proj.getKVEngine() == 'MySQL':

            # tables for annotations and images
            if dbtype==IMAGES_8bit or dbtype==IMAGES_16bit or dbtype==ANNOTATIONS or dbtype==PROBMAP_32bit or dbtype==BITMASK or dbtype==RGB_32bit or dbtype==RGB_64bit:

              for i in datasetcfg.resolutions: 
                newcursor.execute ( "CREATE TABLE res%s ( zindex BIGINT PRIMARY KEY, cube LONGBLOB )" % i )
              newconn.commit()

            elif dbtype==TIMESERIES_4d_8bit or dbtype == TIMESERIES_4d_16bit:

              for i in datasetcfg.resolutions: 
                newcursor.execute ( "CREATE TABLE res%s ( timestamp INT, zindex BIGINT, cube LONGBLOB, PRIMARY KEY(timestamp,zindex))" % i )
                newcursor.execute ( "CREATE TABLE timeseries%s ( z INT, y INT, x INT, t INT,  series LONGBLOB, PRIMARY KEY (z,y,x,t))"%i) 
              newconn.commit()

            # tables for channel dbs
            elif dbtype == CHANNELS_8bit or dbtype == CHANNELS_16bit:
              newcursor.execute ( 'CREATE TABLE channels ( chanstr VARCHAR(255), chanid INT, PRIMARY KEY(chanstr))')
              for i in datasetcfg.resolutions: 
                newcursor.execute ( "CREATE TABLE res%s ( channel INT, zindex BIGINT, cube LONGBLOB, PRIMARY KEY(channel,zindex) )" % i )
              newconn.commit()

          elif proj.getKVEngine() == 'Riak':

            rcli = riak.RiakClient(pb_port=8087, protocol='pbc')
            bucket = rcli.bucket_type("ocp{}".format(proj.getDBType())).bucket(proj.getDBName())
            bucket.set_property('allow_mult',False)
       

          elif proj.getKVEngine() == 'Cassandra':

            cluster = Cluster( [proj.getKVServer()] )
            try:
              session = cluster.connect()

              session.execute ("CREATE KEYSPACE {} WITH REPLICATION = {{ 'class' : 'SimpleStrategy', 'replication_factor' : 1 }}".format(proj.getDBName()), timeout=30)
              session.execute ( "USE {}".format(proj.getDBName()) )
              session.execute ( "CREATE table cuboids ( resolution int, zidx bigint, cuboid text, PRIMARY KEY ( resolution, zidx ) )", timeout=30)
            except Exception, e:
              raise
            finally:
              cluster.shutdown()
            
          else:
            logging.error ("Unknown KV Engine requested: %s" % "RBTODO get name")
            raise OCPCAError ("Unknown KV Engine requested: %s" % "RBTODO get name")


          # tables specific to annotation projects
          if dbtype == ANNOTATIONS or dbtype ==ANNOTATIONS_64bit:

            newcursor.execute("CREATE TABLE ids ( id BIGINT PRIMARY KEY)")

            # And the RAMON objects
            newcursor.execute ( "CREATE TABLE annotations (annoid BIGINT PRIMARY KEY, type INT, confidence FLOAT, status INT)")
            newcursor.execute ( "CREATE TABLE seeds (annoid BIGINT PRIMARY KEY, parentid BIGINT, sourceid BIGINT, cube_location INT, positionx INT, positiony INT, positionz INT)")
            newcursor.execute ( "CREATE TABLE synapses (annoid BIGINT PRIMARY KEY, synapse_type INT, weight FLOAT)")
            newcursor.execute ( "CREATE TABLE segments (annoid BIGINT PRIMARY KEY, segmentclass INT, parentseed INT, neuron INT)")
            newcursor.execute ( "CREATE TABLE organelles (annoid BIGINT PRIMARY KEY, organelleclass INT, parentseed INT, centroidx INT, centroidy INT, centroidz INT)")
            newcursor.execute ( "CREATE TABLE kvpairs ( annoid BIGINT, kv_key VARCHAR(255), kv_value VARCHAR(20000), PRIMARY KEY ( annoid, kv_key ))")

            newconn.commit()

            if proj.getKVEngine() == 'MySQL':
              for i in datasetcfg.resolutions: 
                if exceptions:
                  newcursor.execute ( "CREATE TABLE exc%s ( zindex BIGINT, id BIGINT, exlist LONGBLOB, PRIMARY KEY ( zindex, id))" % i )
                newcursor.execute ( "CREATE TABLE idx%s ( annid BIGINT PRIMARY KEY, cube LONGBLOB )" % i )

              newconn.commit()

            elif proj.getKVEngine() == 'Riak':
              pass

            elif proj.getKVEngine() == 'Cassandra':

              cluster = Cluster( [proj.getKVServer()] )
              try:
                session = cluster.connect()
                session.execute ( "USE {}".format(proj.getDBName()) )
                session.execute( "CREATE table exceptions ( resolution int, zidx bigint, annoid bigint, exceptions text, PRIMARY KEY ( resolution, zidx, annoid ) )", timeout=30)
                session.execute("CREATE table indexes ( resolution int, annoid bigint, cuboids text, PRIMARY KEY ( resolution, annoid ) )", timeout=30)
              except Exception, e:
                raise
              finally:
                cluster.shutdown()

        except MySQLdb.Error, e:
          logging.error ("Failed to create tables for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
          raise OCPCAError ("Failed to create tables for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        except Exception, e:
          raise 
        finally:
          newcursor.close()
          newconn.close()

    # Error, undo the projects table entry
    except:
      sql = "DELETE FROM {0} WHERE token=\'{1}\'".format (ocpcaprivate.projects, token)

      logger.info ( "Could not create project database.  Undoing projects insert. Project %s. SQL=%s" % ( project, sql ))

      with closing(self.conn.cursor()) as cursor:
        try:
          cursor.execute ( sql )
          self.conn.commit()
        except MySQLdb.Error, e:
          logger.error ("Could not undo insert into ocpca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
          logger.error ("Check project database for project not linked to database.")
          raise

        # RBTODO drop tables here?
    


  def deleteOCPCAProj ( self, project ):
    """Create a new ocpca project"""

    sql = "DELETE FROM %s WHERE project=\'%s\'" % ( ocpcaprivate.projects, project ) 

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        conn.rollback()
        logging.error ("Failed to remove project from projects tables %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Failed to remove project from projects tables %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

      self.conn.commit()



  def deleteOCPCADB ( self, token ):

    # load the project
    try:

      proj = self.loadProject ( token )
      # delete line from projects table
      self.deleteOCPCAProj ( proj.getDBName() )

    except Exception, e:
      logger.warning ("Failed to delete project {}".format(e))
      raise
      

    #  try to delete the database anyway
    #  Sometimes weird crashes can get stuff out of sync

    # delete the database
    sql = "DROP DATABASE " + proj.getDBName()

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
        self.conn.commit()
      except MySQLdb.Error, e:
        conn.rollback()
        logger.error ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
#        raise OCPCAError ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))


    #  try to delete the database anyway
    #  Sometimes weird crashes can get stuff out of sync

    if proj.getKVEngine() == 'Cassandra':

      cluster = Cluster( [proj.getKVServer()] )
      try:
        session = cluster.connect()
        session.execute ( "DROP KEYSPACE {}".format(proj.getDBName()), timeout=30 )
      finally:
        cluster.shutdown()


    elif proj.getKVEngine() == 'Riak':

      # connect to cassandra
      rcli = riak.RiakClient(pb_port=8087, protocol='pbc')
      bucket = rcli.bucket_type("ocp{}".format(proj.getDBType())).bucket(proj.getDBName())

      key_list = rcli.get_keys(bucket)

      for k in key_list:
        bucket.delete(k)


  # accessors for RB to fix
  def getDBUser( self ):
    return ocpcaprivate.dbuser
  def getDBPasswd( self ):
    return ocpcaprivate.dbpasswd

  def getTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)
  
  def getIdxTable ( self, resolution ):
    """Return the appropriate Index table for the specified resolution"""
    return "idx"+str(resolution)

  def loadDatasetConfig ( self, dataset ):
    """Query the database for the dataset information and build a db configuration"""
    sql = "SELECT ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale, startwindow, endwindow from %s where dataset = \'%s\'" % (ocpcaprivate.datasets, dataset)


    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:

        logger.error ("Could not query ocpca datasets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Could not query ocpca datasets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

      # get the project information 
      row = cursor.fetchone()

    # if the project is not found.  error
    if ( row == None ):
      logger.warning ( "Dataset %s not found." % ( dataset ))
      raise OCPCAError ( "Dataset %s not found." % ( dataset ))

    [ ximagesz, yimagesz, startslice, endslice, zoomlevels, zscale, startwindow, endwindow ] = row
    return OCPCADataset ( int(ximagesz), int(yimagesz), int(startslice), int(endslice), int(zoomlevels), float(zscale), int(startwindow), int(endwindow) ) 


  #
  # Load the ocpca databse information based on openid
  #
  def getFilteredProjects ( self, openid, filterby, filtervalue ):
    """Load the annotation database information based on the openid"""
    # Lookup the information for the database project based on the openid
    #url = "SELECT * from %s where " + filterby
    #sql = "SELECT * from %s where %s = \'%s\'" % (ocpcaprivate.table, filterby, filtervalue)
    token_desc = ocpcaprivate.token_description;
    proj_tbl = ocpcaprivate.projects;
    if (filterby == ""):
      sql = "SELECT * from %s LEFT JOIN %s on %s.token = %s.token where %s.openid = \'%s\' ORDER BY project" % (ocpcaprivate.projects,token_desc,proj_tbl,token_desc,proj_tbl,openid)
    else:
      sql = "SELECT * from %s LEFT JOIN %s on %s.token = %s.token where %s.openid = \'%s\' and %s.%s = \'%s\' ORDER BY project" % (ocpcaprivate.projects,token_desc,proj_tbl,token_desc, proj_tbl,openid, proj_tbl,filterby, filtervalue.strip())

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
         logger.error ("FAILED TO FILTER")
         raise
      # get the project information
     
      row = cursor.fetchall()

    return row

#*******************************************************************************
  #
  # Load the ocpca databse information based on openid and filter options
  #
  def getFilteredProjs ( self, openid, filterby, filtervalue,dataset ):
    """Load the annotation database information based on the openid"""
    # Lookup the information for the database project based on the openid
    proj_desc = ocpcaprivate.project_description;
    proj_tbl = ocpcaprivate.projects;
    if (filterby == ""):
      sql = "SELECT * from %s LEFT JOIN %s on %s.project = %s.project where %s.openid = \'%s\' and %s.dataset = \'%s\'" % (ocpcaprivate.projects,proj_desc,proj_tbl,proj_desc,proj_tbl,openid,proj_tbl,dataset)
    else:
      sql = "SELECT * from %s LEFT JOIN %s on %s.project = %s.project where %s.openid = \'%s\' and %s.%s = \'%s\' and %s.dataset =\'%s\'" % (ocpcaprivate.projects,proj_desc,proj_tbl,proj_desc, proj_tbl,openid, proj_tbl,filterby, filtervalue.strip(),proj_tbl,dataset)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
         logger.error ("FAILED TO FILTER")
         raise
      # get the project information

      row = cursor.fetchall()

    return row

  #
  # Load Projects created by user ( projadmin)
  #
  def getDatabases ( self, openid):
    """Load the annotation database information based on the openid"""
    # Lookup the information for the database project based on the openid
    
    token_desc = ocpcaprivate.token_description;
    proj_tbl = ocpcaprivate.projects;

    sql = "SELECT distinct(dataset) from %s where openid = \'%s\'"  % (ocpcaprivate.projects,openid)
       
    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
         logger.error ("FAILED TO FILTER")
         raise
      # get the project information

      row = cursor.fetchall()

    return row

  #
  # Load Projects created by user ( projadmin)
  #
  def getDatasets ( self):
    """Load the annotation database information based on the openid"""
    # Lookup the information for the database project based on the openid
    sql = "SELECT * from %s"  % (ocpcaprivate.datasets)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
         logger.error ("FAILED TO FILTER")
         raise
      # get the project information

      row = cursor.fetchall()
    return row

   
#******************************************************************************

  #
  # Update the token for a project
  #
  def updateProject ( self, curtoken ,newtoken):
    """Load the annotation database information based on the openid"""
    sql = "UPDATE %s SET token = \'%s\' where token = \'%s\'" % (ocpcaprivate.projects, newtoken, curtoken)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
         logger.error ("FAILED TO UPDATE")
         raise
      # get the project information                                                                                                          
      self.conn.commit()


    #
    # Add token descriptiton for new projects
    #
  def insertTokenDescription ( self, token ,desc):
    """Add a token description for a new project"""
   # sql = "UPDATE %s SET token = \'%s\' where token = \'%s\'" % (ocpcaprivate.projects, newtoken, curtoken)
    sql = "INSERT INTO %s (token,description) VALUES (\'%s\',\'%s\')" % (ocpcaprivate.token_description, token, desc)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor = self.conn.cursor()
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        logger.error ("FAILED TO INSERT NEW TOKEN DESCRIPTION")
        raise
      # get the project information
      self.conn.commit()

    #
    # Update token descriptiton a project
    #
  def updateTokenDescription ( self, token ,description):
    """Update token description for a project"""
    sql = "UPDATE %s SET description = \'%s\' where token = \'%s\'" % (ocpcaprivate.token_description, description, token)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        logger.error ("FAILED TO UPDATE TOKEN DESCRIPTION")
        raise
      self.conn.commit()

    #
    # Delete row from token_description table
    # Used with delete project
    #
  def deleteTokenDescription ( self, token):
    """Delete entry from token description table"""

    sql = "DELETE FROM  %s where token = \'%s\'" % (ocpcaprivate.token_description, token)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        logger.error ("FAILED TO DELETE TOKEN DESCRIPTION")
        raise
      self.conn.commit()


  def deleteOCPCADatabase ( self, project ):
    #Used for the project management interface
#PYTODO - Check about function
    # Check if there are any tokens for this database
    sql = "SELECT count(*) FROM %s WHERE project=\'%s\'" % ( ocpcaprivate.projects,project )

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        conn.rollback()
        logging.error ("Failed to query projects for database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Failed to query projects for database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      self.conn.commit()
      row = cursor.fetchone()

      if (row == None):
        # delete the database
        sql = "DROP DATABASE " + proj.getDBName()
        
        try:
          cursor.execute ( sql )
        except MySQLdb.Error, e:
          conn.rollback()
          logging.error ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
          raise OCPCAError ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        self.conn.commit()
      else:
        raise OCPCAError ("Tokens still exists. Failed to drop project database")


  def deleteDataset ( self, dataset ):
    #Used for the project management interface
#PYTODO - Check about function
    # Check if there are any tokens for this dataset    
    sql = "SELECT * FROM %s WHERE dataset=\'%s\'" % ( ocpcaprivate.projects, dataset )

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        conn.rollback()
        logging.error ("Failed to query projects for dataset %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Failed to query projects for dataset %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      self.conn.commit()
      row = cursor.fetchone()
      if (row == None):
        sql = "DELETE FROM {0} WHERE dataset=\'{1}\'".format (ocpcaprivate.datasets,dataset)
        try:
          cursor = self.conn.cursor()
          cursor.execute ( sql )
        except MySQLdb.Error, e:
          conn.rollback()
          logging.error ("Failed to delete dataset %d : %s. sql=%s" % (e.args[0], e.args[1], sql))
          raise OCPCAError ("Failed to delete dataset %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        self.conn.commit()
      else:
        raise OCPCAError ("Tokens still exists. Failed to drop project database")

  #
  #  getPublicTokens
  #
  def getPublic ( self ):
    """return a list of public tokens"""

    # RBTODO our notion of a public project is not good so far 
    sql = "select token from {} where public=1".format(ocpcaprivate.projects)

    with closing(self.conn.cursor()) as cursor:
      try:
        cursor.execute ( sql )
      except MySQLdb.Error, e:
        conn.rollback()
        logging.error ("Failed to query projects for public tokens %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        raise OCPCAError ("Failed to query projects for public tokens %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

      return [item[0] for item in cursor.fetchall()]

