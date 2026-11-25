'use strict';
const base = 'https://cdn.jsdelivr.net/pyodide/v0.27.7/full/';
let engine, xlsxReady = false;
const progress = text => self.postMessage({progress:text});
async function initialize() {
  if (engine) return;
  progress('Loading local Python analysis engine (first use requires internet)...');
  importScripts(base + 'pyodide.js');
  const py = await loadPyodide({indexURL:base});
  await py.loadPackage(['pandas', 'pydecimal']);
  // Use the standard pure-Python decimal implementation on WebAssembly.
  await py.runPythonAsync('import sys, _pydecimal\nsys.modules["decimal"] = _pydecimal');
  py.FS.mkdir('/fileguard');
  for (const name of ['analyzer.py','mapping.py','pipeline.py','samples.py','browser_api.py']) {
    const response = await fetch('./engine/' + name);
    if (!response.ok) throw new Error('Missing analysis engine file: ' + name);
    py.FS.writeFile('/fileguard/' + name, await response.text());
  }
  await py.runPythonAsync('import sys\nsys.path.insert(0, "/fileguard")\nimport browser_api, json');
  engine = py;
}
self.onmessage = async ({data}) => {
  try {
    await initialize();
    if (!xlsxReady && [data.storeName,data.supplierName].some(n => n.toLowerCase().endsWith('.xlsx'))) {
      progress('Loading Excel file reader...');
      try { await engine.loadPackage('openpyxl'); await engine.runPythonAsync('import openpyxl'); }
      catch { await engine.loadPackage('micropip'); await engine.runPythonAsync('import micropip\nawait micropip.install("openpyxl==3.1.5")\nimport openpyxl'); }
      xlsxReady = true;
    }
    progress(data.path === '/preview' ? 'Reading catalog files locally...' : 'Analyzing catalog risks locally...');
    const inputs = {fg_action:data.path, fg_store_name:data.storeName, fg_supplier_name:data.supplierName, fg_options:JSON.stringify(data.options)};
    for (const [key,value] of Object.entries(inputs)) engine.globals.set(key,value);
    engine.FS.writeFile('/fileguard/store.bin',new Uint8Array(data.storeData));
    engine.FS.writeFile('/fileguard/supplier.bin',new Uint8Array(data.supplierData));
    let output;
    try {
      output = await engine.runPythonAsync(`from pathlib import Path\nbrowser_api.dispatch(fg_action, fg_store_name, Path('/fileguard/store.bin').read_bytes(), fg_supplier_name, Path('/fileguard/supplier.bin').read_bytes(), json.loads(fg_options))`);
    } finally {
      for (const name of ['store.bin','supplier.bin']) engine.FS.unlink('/fileguard/'+name);
      for (const key of Object.keys(inputs)) engine.globals.delete(key);
    }
    self.postMessage({result:JSON.parse(output)});
  } catch (error) {
    const lines=String(error.message || error).trim().split('\n');
    self.postMessage({error:lines[lines.length-1] || 'Local analysis failed.'});
  }
};
