# Copyright 2014 Open Connectome Project (http://openconnecto.me)
# 
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

import urllib2
import h5py
import tempfile
import random
import numpy as np
from PIL import Image
import cStringIO

import makeunitdb
from ocptype import IMAGE, UINT8, UINT16
from params import Params
from postmethods import postNPZ, getNPZ, getHDF5, postHDF5, getURL, postBlosc, getBlosc
import kvengine_to_test
import site_to_test
SITE_HOST = site_to_test.site


# Test_Jpeg
# 1 - test_get_jpeg

p = Params()
p.token = 'unittest'
p.resolution = 0
p.channels = ['IMAGE1', 'IMAGE2']
p.window = [0,500]
p.channel_type = IMAGE
p.datatype = UINT8
p.voxel = [4.0,4.0,3.0]
#p.args = (3000,3100,4000,4100,500,510)


class Test_Jpeg:

  def setup_class(self):

    makeunitdb.createTestDB(p.token, channel_list=p.channels, channel_type=p.channel_type, channel_datatype=p.datatype)

  def teardown_class(self):
    makeunitdb.deleteTestDB(p.token)


  def test_get_jpeg (self):
    """Test the jpeg volume cutout"""

    p.args = (3000,3100,4000,4100,200,210)
    image_data = np.ones( [2,10,100,100], dtype=np.uint8 ) * random.randint(0,255)
    response = postNPZ(p, image_data)
    
    url = "http://{}/ca/{}/{}/jpeg/{}/{},{}/{},{}/{},{}/".format(SITE_HOST, p.token, p.channels[0], p.resolution, p.args[0], p.args[1], p.args[2], p.args[3], p.args[4], p.args[5])
    data = getURL(url).read()
    posted_data = np.asarray( Image.open(cStringIO.StringIO(data)) )

    image_data = image_data[0,:,:,:].reshape(1000,100)
    assert ( np.array_equal(image_data,posted_data) )
