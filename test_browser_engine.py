"""Native verification of the browser worker's Python boundary (not a WASM test)."""
import json, sys
from pathlib import Path
from io import BytesIO
import pytest
sys.path.insert(0, str(Path(__file__).parent / 'docs' / 'engine'))
from browser_api import dispatch, read_catalog
from samples import sample_bytes
from openpyxl import Workbook

STORE = {'sku':'SKU','product_name':'Title','selling_price':'Price','current_cost':'Cost per item','store_on_hand_qty':'Inventory quantity','barcode':'Barcodes','currency':'currency','pack_size':'pack_size'}
SUPPLIER = {'supplier_sku':'Item No','supplier_product_name':'Description','new_cost':'Wholesale price','supplier_available_qty':'Stock','barcode':'EAN','currency':'currency','pack_size':'Case pack','discontinued':'Discontinued'}
OPTIONS = {'store_mapping':STORE,'supplier_mapping':SUPPLIER,'inventory_config':{'mode':'owned','published_equals_on_hand':True}}

def run(action, a=None, b=None, options=OPTIONS):
    return json.loads(dispatch(action,'store.csv',sample_bytes('store') if a is None else a,'supplier.csv',sample_bytes('supplier') if b is None else b,options))

def test_preview():
    r=run('/preview'); assert r['store']['rows']==50 and r['supplier']['rows']==50
    assert r['store']['example']['SKU']=='FG-001'

def test_analysis():
    r=run('/analyze'); assert r['summary']['total']==50 and r['sample_analysis']
    rows={x['sku']:x for x in r['rows']}; assert rows['FG-004']['status']=='CRITICAL'; assert rows['FG-011']['status']=='REVIEW'; assert rows['FG-017']['status']!='SAFE'
    assert r['summary']['safe']>0

def test_duplicate_headers():
    with pytest.raises(ValueError,match='Duplicate'): read_catalog('x.csv',b'SKU,SKU\n1,2\n')

def test_invalid_rows():
    with pytest.raises(ValueError,match='unexpected'): read_catalog('x.csv',b'SKU,Price\n1,2,3\n')

def test_empty():
    with pytest.raises(ValueError): read_catalog('x.csv',b'')

def test_excel():
    wb=Workbook(); ws=wb.active; ws.append(['sku','price']); ws.append(['001',12.5]); buf=BytesIO(); wb.save(buf)
    r=read_catalog('x.xlsx',buf.getvalue()); assert r.iloc[0]['sku']=='001' and r.iloc[0]['price']=='12.5'

def test_invalid_xlsx():
    with pytest.raises(ValueError,match='Invalid or damaged'): read_catalog('x.xlsx',b'not excel')

def test_size_limit():
    with pytest.raises(ValueError,match='5 MB'): read_catalog('x.csv',b'x'*(5*1024*1024+1))

def test_no_implicit_currency():
    r=run('/analyze',options={'store_mapping':{'sku':'SKU'},'supplier_mapping':{'supplier_sku':'Item No'}})
    assert not r['export_candidates'] and r['summary']['review']>0
