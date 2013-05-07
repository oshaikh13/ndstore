import empaths
import MySQLdb
import h5py
import numpy as np

import emcaprivate
from emcaerror import EMCAError

import logging
logger=logging.getLogger("emca")

# dbtype enumerations
IMAGES_8bit = 1
ANNOTATIONS = 2
CHANNELS_16bit = 3
CHANNELS_8bit = 4

class EMCAProject:
  """Project specific for cutout and annotation data"""

  # Constructor 
  def __init__(self, dbname, dbhost, dbtype, dataset, dataurl, readonly, exceptions ):
    """Initialize the EMCA Project"""
    
    self._dbname = dbname
    self._dbhost = dbhost
    self._dbtype = dbtype
    self._dataset = dataset
    self._dataurl = dataurl
    self._readonly = readonly
    self._exceptions = exceptions
    self._dbtype = dbtype

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
    

  # accessors for RB to fix
  def getDBUser( self ):
    return emcaprivate.dbuser
  def getDBPasswd( self ):
    return emcaprivate.dbpasswd

  def getTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)
  
  def getIdxTable ( self, resolution ):
    """Return the appropriate Index table for the specified resolution"""
    return "idx"+str(resolution)

  def h5Info ( self, h5f ):
    """Populate the HDF5 file with project attributes"""

    projgrp = h5f.create_group ( 'PROJECT' )
    projgrp.create_dataset ( "NAME", (1,), dtype=h5py.special_dtype(vlen=str), data=self._dbname )
    projgrp.create_dataset ( "HOST", (1,), dtype=h5py.special_dtype(vlen=str), data=self._dbhost )
    projgrp.create_dataset ( "TYPE", (1,), dtype=np.uint32, data=self._dbtype )
    projgrp.create_dataset ( "DATASET", (1,), dtype=h5py.special_dtype(vlen=str), data=self._dataset )
    projgrp.create_dataset ( "DATAURL", (1,), dtype=h5py.special_dtype(vlen=str), data=self._dataurl )
    projgrp.create_dataset ( "READONLY", (1,), dtype=bool, data=(False if self._readonly==0 else True))
    projgrp.create_dataset ( "EXCEPTIONS", (1,), dtype=bool, data=(False if self._exceptions==0 else True))

class EMCADataset:
  """Configuration for a dataset"""

  def __init__ ( self, ximagesz, yimagesz, startslice, endslice, zoomlevels, zscale ):
    """Construct a db configuration from the dataset parameters""" 

    self.slicerange = [ startslice, endslice ]

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
  #    if dataset == "bock11" and i == 5:
  #      dbcfg.cubedim[i] = [128, 128, 16]

      # set the image size
      #  the scaled down image rounded up to the nearest cube
      ximgsz = (ximagesz / 2**i) / self.cubedim[i][0] * self.cubedim[i][0]
      yimgsz = (yimagesz / 2**i) / self.cubedim[i][0] * self.cubedim[i][0]
      self.imagesz[i] = [ ximgsz, yimgsz ]

  #
  #  Check that the specified arguments are legal
  #
  def checkCube ( self, resolution, xstart, xend, ystart, yend, zstart, zend ):
    """Return true if the specified range of values is inside the cube"""

    [xmax, ymax] = self.imagesz [ resolution ]

    if (( xstart >= 0 ) and ( xstart <= xend) and ( xend <= self.imagesz[resolution][0]) and\
        ( ystart >= 0 ) and ( ystart <= yend) and ( yend <= self.imagesz[resolution][1]) and\
        ( zstart >= self.slicerange[0] ) and ( zstart <= zend) and ( zend <= (self.slicerange[1]+1))):
      return True
    else:
      return False

#
  #  Return the image size
  #
  def imageSize ( self, resolution ):
    return  [ self.imagesz [resolution], self.slicerange ]

  #
  # H5info
  #
  def h5Info ( self, h5f ):
    """Populate the HDF5 with db configuration information"""

    dcfggrp = h5f.create_group ( 'DATASET' )
    dcfggrp.create_dataset ( "RESOLUTIONS", data=self.resolutions )
    dcfggrp.create_dataset ( "SLICERANGE", data=self.slicerange )
    imggrp = dcfggrp.create_group ( 'IMAGE_SIZE' )
    for k,v in self.imagesz.iteritems():
      imggrp.create_dataset ( str(k), data=v )
    zsgrp = dcfggrp.create_group ( 'ZSCALE' )
    for k,v in self.zscale.iteritems():
      zsgrp.create_dataset ( str(k), data=v )
    cdgrp = dcfggrp.create_group ( 'CUBE_DIMENSION' )
    for k,v in self.cubedim.iteritems():
      cdgrp.create_dataset ( str(k), data=v )


class EMCAProjectsDB:
  """Database for the annotation and cutout projects"""

  def __init__(self):
    """Create the database connection"""

    # Connection info 
    self.conn = MySQLdb.connect (host = emcaprivate.dbhost,
                          user = emcaprivate.dbuser,
                          passwd = emcaprivate.dbpasswd,
                          db = emcaprivate.db )

  #
  # Load the emca databse information based on the token
  #
  def loadProject ( self, token ):
    """Load the annotation database information based on the token"""

    # Lookup the information for the database project based on the token
    sql = "SELECT token, openid, host, project, datatype, dataset, dataurl, readonly, exceptions from %s where token = \'%s\'" % (emcaprivate.projects, token)

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      logger.error ("Could not query emca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Could not query emca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    # get the project information 
    row = cursor.fetchone()

    # if the project is not found.  error
    if ( row == None ):
      logger.warning ( "Project token %s not found." % ( token ))
      raise EMCAError ( "Project token %s not found." % ( token ))

    [token, openid, host, project, dbtype, dataset, dataurl, readonly, exceptions ] = row

    # Create a project object
    proj = EMCAProject ( project, host, dbtype, dataset, dataurl, readonly, exceptions ) 
    proj.datasetcfg = self.loadDatasetConfig ( dataset )

    return proj

  #
  # Create a new dataset
  #
  def newDataset ( self, dsname, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale ):
    """Create a new emca dataset"""

    sql = "INSERT INTO {0} (dataset, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale) VALUES (\'{1}\',\'{2}\',\'{3}\',\'{4}\',{5},\'{6}\',\'{7}\')".format (\
       emcaprivate.datasets, dsname, ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale )

    logger.info ( "Creating new dataset. Name %s. SQL=%s" % ( dsname, sql ))

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      logger.error ("Could not query emca datsets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Could not query emca datsets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    self.conn.commit()


  #
  # Create a new project (annotation or data)
  #
  def newEMCAProj ( self, token, openid, dbhost, project, dbtype, dataset, dataurl, readonly, exceptions, nocreate=False ):
    """Create a new emca project"""

# TODO need to undo the project creation if not totally sucessful
    datasetcfg = self.loadDatasetConfig ( dataset )

    sql = "INSERT INTO {0} (token, openid, host, project, datatype, dataset, dataurl, readonly, exceptions) VALUES (\'{1}\',\'{2}\',\'{3}\',\'{4}\',{5},\'{6}\',\'{7}\',\'{8}\',\'{9}\')".format (\
       emcaprivate.projects, token, openid, dbhost, project, dbtype, dataset, dataurl, int(readonly), int(exceptions) )

    logger.info ( "Creating new project. Host %s. Project %s. SQL=%s" % ( dbhost, project, sql ))

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      logger.error ("Could not query emca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Could not query emca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    self.conn.commit()

    # Exception block around database creation
    try:

      # Make the database unless specified
      if not nocreate: 
       
        # Connect to the new database
        newconn = MySQLdb.connect (host = dbhost,
                              user = emcaprivate.dbuser,
                              passwd = emcaprivate.dbpasswd )

        newcursor = newconn.cursor()
      

        # Make the database and associated emca tables
        sql = "CREATE DATABASE %s;" % project
       
        try:
          newcursor.execute ( sql )
        except MySQLdb.Error, e:
          logger.error ("Failed to create database for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
          raise EMCAError ("Failed to create database for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

        newconn.commit()

        # Connect to the new database
        newconn = MySQLdb.connect (host = dbhost,
                              user = emcaprivate.dbuser,
                              passwd = emcaprivate.dbpasswd,
                              db = project )

        newcursor = newconn.cursor()

        sql = ""

        # tables for annotations and images
        if dbtype == IMAGES_8bit or dbtype == ANNOTATIONS:

          for i in datasetcfg.resolutions: 
            sql += "CREATE TABLE res%s ( zindex BIGINT PRIMARY KEY, cube LONGBLOB );\n" % i

        # tables for channel dbs
        if dbtype == CHANNELS_8bit or dbtype == CHANNELS_16bit:
          for i in datasetcfg.resolutions: 
            sql += "CREATE TABLE res%s ( channel INT, zindex BIGINT, cube LONGBLOB, PRIMARY KEY(channel,zindex) );\n" % i

        # tables specific to annotation projects
        if dbtype == ANNOTATIONS:

          sql += "CREATE TABLE ids ( id BIGINT PRIMARY KEY);\n"

          # And the RAMON objects
          sql += "CREATE TABLE annotations (annoid BIGINT PRIMARY KEY, type INT, confidence FLOAT, status INT);\n"
          sql += "CREATE TABLE seeds (annoid BIGINT PRIMARY KEY, parentid BIGINT, sourceid BIGINT, cube_location INT, positionx INT, positiony INT, positionz INT);\n"
          sql += "CREATE TABLE synapses (annoid BIGINT PRIMARY KEY, synapse_type INT, weight FLOAT);\n"
          sql += "CREATE TABLE segments (annoid BIGINT PRIMARY KEY, segmentclass INT, parentseed INT, neuron INT);\n"
          sql += "CREATE TABLE organelles (annoid BIGINT PRIMARY KEY, organelleclass INT, parentseed INT, centroidx INT, centroidy INT, centroidz INT);\n"
          sql += "CREATE TABLE kvpairs ( annoid BIGINT, kv_key VARCHAR(255), kv_value VARCHAR(64000), PRIMARY KEY ( annoid, kv_key ));\n"

          for i in datasetcfg.resolutions: 
            if exceptions:
              sql += "CREATE TABLE exc%s ( zindex BIGINT, id INT, exlist LONGBLOB, PRIMARY KEY ( zindex, id));\n" % i
            sql += "CREATE TABLE idx%s ( annid BIGINT PRIMARY KEY, cube LONGBLOB );\n" % i

        try:
          cursor = newconn.cursor()
          newcursor.execute ( sql )
        except MySQLdb.Error, e:
          logging.error ("Failed to create tables for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
          raise EMCAError ("Failed to create tables for new project %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    # Error, undo the projects table entry
    except:
      sql = "DELETE FROM {0} WHERE token=\'{1}\'".format (emcaprivate.projects, token)

      logger.info ( "Could not create project database.  Undoing projects insert. Project %s. SQL=%s" % ( project, sql ))

      try:
        cursor = self.conn.cursor()
        cursor.execute ( sql )
        self.conn.commit()
      except MySQLdb.Error, e:
        logger.error ("Could not undo insert into emca projects database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
        logger.error ("Check project database for project not linked to database.")
        raise

    

  def deleteEMCAProj ( self, token ):
    """Create a new emca project"""

    proj = self.loadProject ( token )
    sql = "DELETE FROM %s WHERE token=\'%s\'" % ( emcaprivate.projects, token ) 

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      conn.rollback()
      logging.error ("Failed to remove project from projects tables %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Failed to remove project from projects tables %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    self.conn.commit()


  def deleteEMCADB ( self, token ):

    # load the project
    proj = self.loadProject ( token )

    # delete line from projects table
    self.deleteEMCAProj ( token )

    # delete the database
    sql = "DROP DATABASE " + proj.getDBName()

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      conn.rollback()
      logging.error ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Failed to drop project database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    self.conn.commit()

  # accessors for RB to fix
  def getDBUser( self ):
    return emcaprivate.dbuser
  def getDBPasswd( self ):
    return emcaprivate.dbpasswd

  def getTable ( self, resolution ):
    """Return the appropriate table for the specified resolution"""
    return "res"+str(resolution)
  
  def getIdxTable ( self, resolution ):
    """Return the appropriate Index table for the specified resolution"""
    return "idx"+str(resolution)

  def loadDatasetConfig ( self, dataset ):
    """Query the database for the dataset information and build a db configuration"""

    sql = "SELECT ximagesize, yimagesize, startslice, endslice, zoomlevels, zscale from %s where dataset = \'%s\'" % (emcaprivate.datasets, dataset)

    try:
      cursor = self.conn.cursor()
      cursor.execute ( sql )
    except MySQLdb.Error, e:
      logger.error ("Could not query emca datasets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))
      raise EMCAError ("Could not query emca datasets database %d: %s. sql=%s" % (e.args[0], e.args[1], sql))

    # get the project information 
    row = cursor.fetchone()

    # if the project is not found.  error
    if ( row == None ):
      logger.warning ( "Dataset %s not found." % ( dataset ))
      raise EMCAError ( "Dataset %s not found." % ( dataset ))

    [ ximagesz, yimagesz, startslice, endslice, zoomlevels, zscale ] = row
    return EMCADataset ( ximagesz, yimagesz, startslice, endslice, zoomlevels, zscale ) 



