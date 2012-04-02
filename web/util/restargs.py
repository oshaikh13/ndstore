#
#  Check the formatting of RESTful arguments.
#  Shared by cutout and annotation services.
#

import sys
import re
import os

import dbconfig


#
# General rest argument processing exception
#
class RESTRangeError(Exception):
  """Arguments exceed image/voxel bounds"""
  def __init__(self, value):
    self.value = value
  def __str__(self):
    return repr(self.value)

class RESTBadArgsError(Exception): 
  """Illegal arguments"""
  def __init__(self, value):
    self.value = value
  def __str__(self):
    return repr(self.value)

class RESTTokenError(Exception):
  """Invalid annotation token"""
  def __init__(self, value):
    self.value = value
  def __str__(self):
    return repr(self.value)


class BrainRestArgs:


  # __init__
  def __init__ ( self ):
    """Set resolution to -1 to make things break if one doesn't set resolution prior to 
       calling an args parsing function.  I don't like this, but it works."""
    self._resolution = -1

  # Accessors to get corner and dimensions
  def getCorner (self):
    return self._corner

  def getDim (self):
   return self._dim
   
  def getResolution (self):
   return self._resolution


  #
  # setResolution : used with annotation in which resolution is stored by token
  #
  def setResolution(self, resolution):
    """Set the resolution.  Used when annotating."""
    self._resolution=resolution

  #
  # resolutionArgs: 
  #
  def resolutionArg ( self, restargs, dbcfg ):
    """Set resolution.  Strip off resolutoin and return the rest of the args."""

    [resolution, sym, cutoutargs] = restargs.partition ('/') 
#RBTODO
#    if resolution not in dbconfig.resolutions
    self._resolution = int(resolution)
    return cutoutargs


  #
  #  Process cutout arguments
  #
  def cutoutArgs2 ( self, imageargs, dbcfg ):
    """Process REST arguments for an cutout plane request
       Deprecated functions.  Use cutoutArgs.
       You must have set the resolution prior to calling this function."""

    assert ( self._resolution != -1 )

    # expecting an argument of the form /resolution/x1,x2/y1,y2/z1,z2/

    restargs = imageargs.split('/')

    if len ( restargs ) == 4:
      [ xdimstr, ydimstr, zdimstr, rest ]  = restargs
      globalcoords = False
    elif len ( restargs ) == 5:
      [ xdimstr, ydimstr, zdimstr, rest, other ]  = restargs
      globalcoords = True
    else:
      raise RESTBadArgsError ( "Incorrect command string" )

    # Check that the arguments are well formatted
    if not re.match ('[0-9]+,[0-9]+$', xdimstr) or\
       not re.match ('[0-9]+,[0-9]+$', ydimstr) or\
       not re.match ('[0-9]+,[0-9]+$', zdimstr):
      raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

    z1s,z2s = zdimstr.split(',')
    y1s,y2s = ydimstr.split(',')
    x1s,x2s = xdimstr.split(',')

    x1i = int(x1s)
    x2i = int(x2s)
    y1i = int(y1s)
    y2i = int(y2s)
    z1i = int(z1s)
    z2i = int(z2s)

    # Convert to local coordinates if global specified
    if ( globalcoords ):
      x1i = int ( float(x1i) / float( 2**(self._resolution-dbcfg.baseres)))
      x2i = int ( float(x2i) / float( 2**(self._resolution-dbcfg.baseres)))
      y1i = int ( float(y1i) / float( 2**(self._resolution-dbcfg.baseres)))
      y2i = int ( float(y2i) / float( 2**(self._resolution-dbcfg.baseres)))

    # Check arguments for legal values
    if not ( dbcfg.checkCube ( self._resolution, x1i, x2i, y1i, y2i, z1i, z2i )):
      raise RESTRangeError ( "Illegal range. Image size:" +  str(dbcfg.imageSize( self._resolution )))

    self._corner=[x1i,y1i,z1i-dbcfg.slicerange[0]]
    self._dim=[x2i-x1i,y2i-y1i,z2i-z1i ]


  def cutoutArgs ( self, xstr, ystr, zstr, dbcfg, globalcoords=False ):
    """Process REST arguments for a cutout request.
       This takes the x y and z strs from a partition on '/'.
       Each is of the form  xxx,xxx
        Use this instead of cutoutArgs.  Eventually we want to migrate
        all interfaces to use this."""

    # Check that the arguments are well formatted
    if not re.match ('[0-9]+,[0-9]+$', xstr) or\
       not re.match ('[0-9]+,[0-9]+$', ystr) or\
       not re.match ('[0-9]+,[0-9]+$', zstr):
      raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

    z1s,z2s = zstr.split(',')
    y1s,y2s = ystr.split(',')
    x1s,x2s = xstr.split(',')

    x1i = int(x1s)
    x2i = int(x2s)
    y1i = int(y1s)
    y2i = int(y2s)
    z1i = int(z1s)
    z2i = int(z2s)

    # Convert to local coordinates if global specified
    if ( globalcoords ):
      x1i = int ( float(x1i) / float( 2**(self._resolution-dbcfg.baseres)))
      x2i = int ( float(x2i) / float( 2**(self._resolution-dbcfg.baseres)))
      y1i = int ( float(y1i) / float( 2**(self._resolution-dbcfg.baseres)))
      y2i = int ( float(y2i) / float( 2**(self._resolution-dbcfg.baseres)))

    # Check arguments for legal values
    if not ( dbcfg.checkCube ( self._resolution, x1i, x2i, y1i, y2i, z1i, z2i )):
      raise RESTRangeError ( "Illegal range. Image size:" +  str(dbcfg.imageSize( self._resolution )))

    self._corner=[x1i,y1i,z1i-dbcfg.slicerange[0]]
    self._dim=[x2i-x1i,y2i-y1i,z2i-z1i ]


  #
  #  **Image return a readable png object
  #    where ** is xy, xz, yz
  #
  def xyArgs ( self, imageargs, dbcfg ):
    """Process REST arguments for an xy plane request.
       You must have set the resolution prior to calling this function."""

    assert ( self._resolution != -1 )

    rangeargs = imageargs.split('/')

    if len ( rangeargs ) == 4:
      [ xdimstr, ydimstr, zstr, rest ]  = rangeargs
      globalcoords = False
    elif len ( rangeargs ) == 5:
      [ xdimstr, ydimstr, zstr, rest, other ]  = rangeargs
      globalcoords = True
    else:
      raise RESTBadArgsError ("Wrong number of arguments for xyArgs %s" % rangeargs)

    # expecting an argument of the form /resolution/x1,x2/y1,y2/z/
    # Check that the arguments are well formatted
    if not re.match ('[0-9]+,[0-9]+$', xdimstr) or\
       not re.match ('[0-9]+,[0-9]+$', ydimstr) or\
       not re.match ('[0-9]+$', zstr):
      raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

    x1s,x2s = xdimstr.split(',')
    y1s,y2s = ydimstr.split(',')

    x1i = int(x1s)
    x2i = int(x2s)
    y1i = int(y1s)
    y2i = int(y2s)
    z = int(zstr)

    # Convert to local coordinates if global specified
    if ( globalcoords ):
      x1i = int ( float(x1i) / float( 2**(self._resolution-dbcfg.baseres)))
      x2i = int ( float(x2i) / float( 2**(self._resolution-dbcfg.baseres)))
      y1i = int ( float(y1i) / float( 2**(self._resolution-dbcfg.baseres)))
      y2i = int ( float(y2i) / float( 2**(self._resolution-dbcfg.baseres)))

    # Check arguments for legal values
    if not ( dbcfg.checkCube ( self._resolution, x1i, x2i, y1i, y2i, z, z )):
      raise RESTBadArgsError ("Range exceeds data boundaries" % rangeargs)

    self._corner=[x1i,y1i,z-dbcfg.slicerange[0]]
    self._dim=[x2i-x1i,y2i-y1i,1]


    
  def xzArgs ( self, imageargs, dbcfg ):
    """Process REST arguments for an xz plane request
       You must have set the resolution prior to calling this function."""

    assert ( self._resolution != -1 )

    rangeargs = imageargs.split('/')

    if len ( rangeargs ) == 4:
      [ xdimstr, ystr, zdimstr, rest ]  = rangeargs
      globalcoords = False
    elif len ( rangeargs ) == 5:
      [ xdimstr, ystr, zdimstr, rest, other ]  = rangeargs
      globalcoords = True
    else:
      raise RESTBadArgsError ("Wrong number of arguments for xzArgs %s" % rangeargs)

    # expecting an argument of the form /resolution/x1,x2/y1,y2/z/
    # Check that the arguments are well formatted
    if not re.match ('[0-9]+,[0-9]+$', xdimstr) or\
       not re.match ('[0-9]+$', ystr) or\
       not re.match ('[0-9]+,[0-9]+$', zdimstr):
      raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

    x1s,x2s = xdimstr.split(',')
    z1s,z2s = zdimstr.split(',')

    x1i = int(x1s)
    x2i = int(x2s)
    y = int(ystr)
    z1i = int(z1s)
    z2i = int(z2s)

    # Convert to local coordinates if global specified
    if ( globalcoords ):
      x1i = int ( float(x1i) / float( 2**(self._resolution-dbcfg.baseres)))
      x2i = int ( float(x2i) / float( 2**(self._resolution-dbcfg.baseres)))
      y = int ( float(y) / float( 2**(self._resolution-dbcfg.baseres)))

    # Check arguments for legal values
    if not dbcfg.checkCube ( self._resolution, x1i, x2i, y, y, z1i, z2i )\
       or y >= dbcfg.imagesz[self._resolution][1]:
      raise RESTBadArgsError ("Range exceeds data boundaries" % rangeargs)

    self._corner=[x1i,y,z1i-dbcfg.slicerange[0]]
    self._dim=[x2i-x1i,1,z2i-z1i ]


  def yzArgs ( self, imageargs, dbcfg ):
    """Process REST arguments for an yz plane request
       You must have set the resolution prior to calling this function."""

    assert ( self._resolution != -1 )

    rangeargs = imageargs.split('/')

    if len ( rangeargs ) == 4:
      [ xstr, ydimstr, zdimstr, rest ]  = rangeargs
      globalcoords = False
    elif len ( rangeargs ) == 5:
      [ xstr, ydimstr, zdimstr, rest, other ]  = rangeargs
      globalcoords = True
    else:
      raise RESTBadArgsError ("Wrong number of arguments for yzArgs %s" % rangeargs)

    # expecting an argument of the form /resolution/x/y1,y2/z1,z2/
    # Check that the arguments are well formatted
    if not re.match ('[0-9]+$', xstr) or\
       not re.match ('[0-9]+,[0-9]+$', ydimstr) or\
       not re.match ('[0-9]+,[0-9]+$', zdimstr):
      raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

    y1s,y2s = ydimstr.split(',')
    z1s,z2s = zdimstr.split(',')

    x = int(xstr)
    y1i = int(y1s)
    y2i = int(y2s)
    z1i = int(z1s)
    z2i = int(z2s)

    # Convert to local coordinates if global specified
    if ( globalcoords ):
      x = int ( float(x) / float( 2**(self._resolution-dbcfg.baseres)))
      y1i = int ( float(y1i) / float( 2**(self._resolution-dbcfg.baseres)))
      y2i = int ( float(y2i) / float( 2**(self._resolution-dbcfg.baseres)))


    #RBTODO need to make a dbconfig object 
    # Check arguments for legal values
    if not dbcfg.checkCube ( self._resolution, x, x, y1i, y2i, z1i, z2i  )\
       or  x >= dbcfg.imagesz[self._resolution][0]:
      raise RESTBadArgsError ("Range exceeds data boundaries" % rangeargs)

    self._corner=[x,y1i,z1i-dbcfg.slicerange[0]]
    self._dim=[1,y2i-y1i,z2i-z1i ]


# Unbound functions  not part of the class object


#
#  Process cutout arguments
#
def voxel ( imageargs, dbcfg, resolution ):
  """Process REST arguments for a single"""

  rangeargs = imageargs.split('/')

  if len ( rangeargs ) == 4:
    [ xstr, ystr, zstr, rest ]  = rangeargs
  else:
    raise RESTBadArgsError ("Wrong number of arguments for voxel %s" % rangeargs)

  # expecting an argument of the form /resolution/x/y1,y2/z1,z2/
  # Check that the arguments are well formatted
  if not re.match ('[0-9]+$', xstr) or\
     not re.match ('[0-9]+$', ystr) or\
     not re.match ('[0-9]+$', zstr):
    raise RESTBadArgsError ("Non-numeric range argument" % rangeargs)

  x = int(xstr)
  y = int(ystr)
  z = int(zstr)

  # Check arguments for legal values
  if not ( dbcfg.checkCube ( resolution, x, x, y, y, z, z )):
    raise RESTRangeError ( "Illegal range. Image size:" +  str(dbcfg.imageSize( self._resolution )))

  return [ x,y,z ]


#
#  Process cutout arguments
#
def conflictOption  ( imageargs ):
  """Parse the conflict resolution string"""

  restargs = imageargs.split('/')
  if len (restargs) > 0:
    if restargs[0] == 'preserve':
      return 'P'
    elif restargs[0] == 'except':
      return 'E'
    else:
      return 'O'



