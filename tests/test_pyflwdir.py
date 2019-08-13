# -*- coding: utf-8 -*-
# Author: Dirk Eilander (contact: dirk.eilander@deltares.nl)
# August 2019

"""Tests for the pyflwdir module.
"""
import pytest
import numba
import time
rtsys = numba.runtime.rtsys

import numpy as np
import rasterio 
import xarray as xr

import pyflwdir
from pyflwdir import FlwdirRaster
from pyflwdir.core import fd
from pyflwdir.utils import flwdir_check


with rasterio.open(r'./tests/data/flwdir.tif', 'r') as src:
    raster = src.read(1)
    transform = src.transform
    nodata = src.nodata
    crs = src.crs
    prof = src.profile
idx0 = np.uint32(864)
prof.update(nodata=-9999, dtype=np.int32)

# def test_something():
#     assert True

# def test_with_error():
#     with pytest.raises(ValueError):
#         # Do something that raises a ValueError
#         raise(ValueError)

# # Fixture example
# @pytest.fixture
# def an_object():
#     return {}

# test object
def test_object():
    flwdir = FlwdirRaster(raster.copy())
    assert isinstance(flwdir, FlwdirRaster)

def test_flwdir_repair():
    flwdir = FlwdirRaster(raster.copy())
    assert flwdir.isvalid()
    lst, hasloops = flwdir_check(flwdir._data_flat, flwdir.shape)
    assert len(lst) == 110 and not hasloops
    flwdir.repair() # repair edges
    lst, hasloops = flwdir_check(flwdir._data_flat, flwdir.shape)
    assert len(lst) == 0 and not hasloops
    # create loop
    idx = 450 
    idx_us = fd.us_indices(idx, flwdir._data_flat, flwdir.shape)[0]
    flwdir[idx] = fd.idx_to_dd(idx, idx_us, flwdir.shape)
    lst, hasloops = flwdir_check(flwdir._data_flat, flwdir.shape)
    assert hasloops
    flwdir.repair() # repair loop
    lst, hasloops = flwdir_check(flwdir._data_flat, flwdir.shape)
    assert len(lst) == 0 and not hasloops

def test_setup_network():
    flwdir = FlwdirRaster(raster.copy())
    flwdir.repair()
    flwdir.setup_network()
    assert flwdir._rnodes[0].dtype == np.uint32
    assert len(flwdir._rnodes) == len(flwdir._rnodes_up) == 174
    tot_n = np.sum([np.sum(n != np.uint32(-1)) for n in flwdir._rnodes_up]) + flwdir._rnodes[-1].size
    assert tot_n == flwdir.size

def test_delineate_basins():
    flwdir = FlwdirRaster(raster.copy())
    flwdir.repair() # after repair the total bbox should be equal to flwdir.bbox
    idx = flwdir.get_pits()
    basins, bboxs = flwdir.delineate_basins()
    xmin, ymin = bboxs.min(axis=0)[[0,1]]
    xmax, ymax = bboxs.max(axis=0)[[2,3]]
    assert np.all((xmin, ymin, xmax, ymax) == flwdir.bounds)
    assert bboxs.shape[0] == idx.size
    assert np.all(np.unique(basins).size==idx.size) # single basin index
    
    # check bboxs of main basin
    basins, bboxs = flwdir.delineate_basins(idx0)
    assert np.all(bboxs[0] == flwdir.bounds)
    assert np.all(np.unique(basins).size==1+1) # single basin index plus background value
    assert np.sum(basins) == 3045

def test_basin_maps():
    # test single basin
    flwdir = FlwdirRaster(raster.copy())
    flwdir.setup_network(idx0)
    basins = flwdir.basin_map()
    assert np.all(np.unique(basins[basins!=0])==1) # single basin index
    assert np.sum(basins) == 3045
    np.random.seed(0)
    idxs = np.where(basins.ravel())[0]
    idx = np.concatenate((
        idxs[np.random.randint(0, np.sum(basins), 18)],
        np.array([idx0])
        )
    )
    basins2 = flwdir.basin_map(idx=idx, values=idx, dtype=np.int32)
    assert np.sum(basins2!=0) == 3045
    assert np.unique(basins2).size == 20 # 19 subbasins + background zero
    # with rasterio.open(r'./tests/data/basins.tif', 'w', **prof) as dst:
    #     dst.write(basins2, 1)

def test_stream_order():
    # 
    flwdir = FlwdirRaster(raster.copy())
    flwdir.setup_network(idx0)
    stream_order = flwdir.stream_order()
    assert stream_order.dtype == np.int8
    assert stream_order.min() == -1
    assert np.unique(stream_order).size == 7
    assert np.sum(stream_order>0) == 3045
    assert np.sum(stream_order==6) == 88

    # flwdir = FlwdirRaster(raster.copy())
    # flwdir.repair()
    # stream_order = flwdir.stream_order()
    # prof.update(dtype=stream_order.dtype, nodata=-1)
    # with rasterio.open(r'./tests/data/stream_order.tif', 'w', **prof) as dst:
    #     dst.write(stream_order, 1)

def test_uparea():
    # test as if metres with identity transform
    flwdir = FlwdirRaster(raster.copy(), crs=28992) #RD New - Netherlands [metres]
    flwdir.setup_network(idx0)
    upa = flwdir.upstream_area()
    tot_n = np.sum([np.sum(n != np.uint32(-1)) for n in flwdir._rnodes_up]) + flwdir._rnodes[-1].size
    assert np.round(upa.max()*1e6,2) == tot_n == 3045.00
    # test in latlon with identity transform
    flwdir = FlwdirRaster(raster.copy())
    flwdir.setup_network(idx0)
    upa = flwdir.upstream_area()
    assert np.round(upa.max(),2) == 31610442.85

def test_riv_shape():
    flwdir = FlwdirRaster(raster.copy(), crs=crs, transform=transform)
    flwdir.setup_network(idx0)
    gdf = flwdir.stream_shape()
    gdf.to_file('./tests/data/rivers.shp')

def test_upscale():
    with rasterio.open(r'./tests/data/flwdir2.tif', 'r') as src:
        data2 = src.read(1)
    flwdir = FlwdirRaster(raster, crs=crs, transform=transform, copy=True)
    flwdir.repair()
    flwdir2, outlets = flwdir.upscale(2)
    assert flwdir2._data.size*4 == flwdir._data.size
    assert np.all(flwdir2._data == data2)
    # stream_order = flwdir2.stream_order()
    # gdf = flwdir2.stream_shape()
    # gdf.to_file('./tests/data/rivers2.shp')
    # prof = dict(
    #     driver='GTiff',
    #     dtype=flwdir2._data.dtype,
    #     height=flwdir2.shape[0],
    #     width=flwdir2.shape[1],
    #     transform=flwdir2.transform,
    #     crs=flwdir2.crs,
    #     nodata=247,
    #     count=1,
    # )
    # with rasterio.open(r'./tests/data/flwdir2.tif', 'w', **prof) as dst:
    #     dst.write(flwdir2._data, 1)

def check_memory_time():
    # raster = xr.open_dataset(r'd:\work\flwdir_scaling\03sec\test_sel_idx74.nc')['dir'].load().values
    raster = xr.open_dataset(r'/media/data/hydro_merit_1.0/03sec/test_sel_idx74.nc')['dir'].load().values
    idx0 = np.uint32(8640959)
    print(rtsys.get_allocation_stats())
    
    print('initialize')
    flwdir = FlwdirRaster(raster)
    print(rtsys.get_allocation_stats())

    print('setup network')
    start = time.time()    
    pyflwdir.network.setup_dd(np.asarray([idx0], dtype=np.uint32), flwdir._data_flat, flwdir.shape)
    end = time.time()
    print(f"Elapsed (before compilation) = {(end - start):.6f} s")
    print(rtsys.get_allocation_stats())
    for i in range(3):
        start = time.time()
        pyflwdir.network.setup_dd(np.asarray([idx0], dtype=np.uint32), flwdir._data_flat, flwdir.shape)
        end = time.time()
        print(f"Elapsed (after compilation) = {(end - start):.6f} s")
        print(rtsys.get_allocation_stats())
    
    # print('basin delineation')
    # basins = flwdir.basin_map()
    # print(rtsys.get_allocation_stats())
    
    # print('basin bouhds')
    # bounds = flwdir.delineate_basins()
    # print(rtsys.get_allocation_stats())

    # print('upastream area')
    # upa = flwdir.upstream_area()
    # print(rtsys.get_allocation_stats())

    # print('stream oder')
    # stro = flwdir.stream_order()
    # print(rtsys.get_allocation_stats())


if __name__ == "__main__":
    # import pdb; pdb.set_trace()
    # check_memory_time()
    # print('finalize')
    # print(rtsys.get_allocation_stats())
    # test_setup_network()
    # test_flwdir_repair()
    # test_delineate_basins()
    # test_basin_maps()
    # test_uparea()
    # test_stream_order()
    # test_riv_shape()
    test_upscale()
    pass
