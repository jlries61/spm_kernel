from IPython.display import Image, SVG
from IPython.display import display, HTML
from metakernel import MetaKernel, ProcessMetaKernel, pexpect, u
from metakernel.process_metakernel import TextOutput
from metakernel.process_metakernel import REPLWrapper
import io
import re
import os
import xmltodict
import xml.parsers.expat
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import logging
from base64 import b64encode
import tempfile
from pexpect import EOF

from spm_kernel.version import __version__

__SPM__ = 'spmu'
__prompt__ = ' >'
__echo__ = True

try:
    FileNotFoundError
except NameError:
    # Python 2
    FileNotFoundError = OSError

class SPMKernel(ProcessMetaKernel):
  implementation = 'SPM Kernel'
  implementation_version = __version__
  language = 'SPM'
  language_version = '8.3'
  language_info = {'name': 'SPM',
                   'codemirror_mode': 'shell',
                   'mimetype': 'text/x-sh',
                   'file_extension': '.cmd'}
  _first = True
  inline_plotting = True

  @property
  def banner(self):
    if self._banner is None:
      self._banner = check_output([__SPM__, '--L']).decode('utf-8')
      return self._banner

  def __init__(self, *args, **kwargs):
    MetaKernel.__init__(self, *args, **kwargs)
    self.wrapper = None
    self.wrapper = self.makeWrapper()
    #self.log.setLevel(logging.DEBUG)

  def makeWrapper(self):
    return REPLWrapper(__SPM__, __prompt__, None)

  def extract(self, input, starttag, endtag):
    start = input.index(starttag)
    finish = input.index(endtag)
    finlen = len(endtag)
    return input[start : finish + finlen]

  def display_figure(self, fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi='figure')
    width = fig.get_figwidth() * fig.dpi
    data = "<img src='data:image/png;base64,{0}' width={1}/>"
    data = data.format(b64encode(buf.getvalue()).decode('utf-8'), width)
    super(SPMKernel, self).Display(HTML(data))

  def display_table(self, input, pattern):
    found = False
    inline = input.splitlines()
    iline = 0
    nline = len(inline)
    maxline = nline - 1
    title = ""
    for line in inline:
      if re.search(pattern, line):
        if iline > 0 and re.search("^ =+$", inline[iline - 1]) and re.search("^ =+$", inline[iline + 1]):
          title = line
          found = True
          break
      iline = iline + 1
    if not found:
      return found
    for i in range(iline, maxline):
      if re.search("^ -+$", inline[i]):
        headline = inline[i - 1]
        iline = i + 1
        break
    maxlen = len(headline)
    if maxlen == 0:
      return False
    table = []
    nlines = 0
    line = ""
    for i in range(iline, maxline):
      if len(inline[i]) == 0:
        break
      if len(line) == 0 or re.search(",$", line):
        line = line + inline[i]
      else:
        line = re.sub(", +", ", ", line)
        linelen = len(line)
        if linelen > maxlen:
          maxlen = linelen
        table.append(line)
        nlines = nlines + 1
        line = inline[i]
    if len(line) > 0:
      table.append(line)
      nlines = nlines + 1
    startcol = [1]
    endcol = []
    lastline = nlines
    footline = nlines
    iline = 0
    for line in table:
      icol = 0
      if re.search("^ -+$", line):
        footline = iline
        break
      incol = False
      for col in range(1, len(line)-1):
        if line[col] == " ":
          if incol and line[col-1] != ",":
            incol = False
            if icol >= len(startcol) - 1:
              endcol.append(col)
              if col < len(headline) and headline[col] == " ":
                startcol.append(col+1)
              else:
                startcol.append(col)
            elif col > endcol[icol]:
              endcol[icol] = col
            icol = icol + 1
        else:
          incol = True
      iline = iline + 1
    endcol.append(maxlen)
    ncol = len(startcol)
    head = []
    for icol in range(ncol):
      head.append(headline[startcol[icol]:endcol[icol]])
    body = []
    for iline in range(footline):
      line = table[iline]
      cell=[]
      for icol in range(ncol):
        cell.append(line[startcol[icol]:endcol[icol]])
      body.append(cell)
    foot = []
    if nlines > footline:
      for iline in range(footline + 1, nlines):
        line = table[iline]
        cell = []
        for icol in range(ncol):
          cell.append(line[startcol[icol]:endcol[icol]])
        foot.append(cell)
    html="<table>"
    if len(title) > 0:
      html = html + "<caption>" + title + "</caption>"
    html = html + "<thead><tr>"
    for header in head:
      html = html + "<th>" + header + "</th>"
    html = html + "</tr></thead><tbody>"
    for row in body:
      html = html + "<tr>"
      for cell in row:
        html = html + "<td>" + cell + "</td>"
      html + "</tr>"
    html = html + "</tbody>"
    if len(foot) > 0:
      html = html + "<tfoot>"
      for row in foot:
        html = html + "<tr>"
        html = html + "<th>" + row[0] + "</th>"
        for icol in range(1, ncol):
          html = html + "<td>" + row[icol] + "</td>"
        html = html + "</tr>"
      html = html + "</tfoot>"
    html = html + "</table>"
    super(SPMKernel, self).Display(HTML(html))
    return found

  def display_varimp(self, doc):
    models = [];
    for modtype in ("MiningModel", "TreeModel", "RegressionModel"):
      if modtype in doc["PMML"]:
        mod = doc["PMML"][modtype]
        if type(mod) is list:
          models.extend(mod)
        else:
          models.append(mod)
    impsum = {}
    nmod = 0
    for mod in models:
      if mod["@algorithmName"] in ("Logit", "Regress", "2SLS"):
        continue
      nmod = nmod + 1
      schema = mod["MiningSchema"]
      fields = schema["MiningField"]
      for field in fields:
        name = field["@name"]
        usageType = field["@usageType"]
        if usageType == "active":
          if name not in impsum:
            impsum[name] = 0
          if "@importance" in field:
            impsum[name] = impsum[name] + 100*float(field["@importance"])
          else:
            impsum[name] = impsum[name] + 100
    varimp = {}
    for name in impsum.keys():
      varimp[name]=impsum[name]/nmod
    varimp_series = pd.Series(varimp).sort_values(ascending=True)
    predname=varimp_series.keys()
    fig = plt.figure()
    varimp_series.plot.barh(title="Variable Importances", color="blue")
    plt.xlabel("Importance")
    plt.ylabel("Predictor Name")
    self.display_figure(fig)

  def SPMPlots(self,doc):
    plots = doc["SPMPlots"]["Plot"]
    datadict=doc["SPMPlots"]["DataDictionary"]
    datafields=datadict["DataField"]
    datatype={}
    optype={}
    cat={}
    for datafield in datafields:
      datatype[datafield["@name"]]=datafield["@dataType"]
      optype[datafield["@name"]]=datafield["@optype"]
      if datafield["@optype"] == "categorical":
        cat[datafield["@name"]]=[]
        vallist=datafield["Value"]
        for value in vallist:
          cat[datafield["@name"]].append(value["@value"])
    for plot in plots:
      plottype = plot["@Type"]
      modtype = plot["@Model"]
      nrecords = int(plot["@NRecords"])
      ncoord = int(plot["@NCoordinates"])
      coord = plot["Coordinate"]
      if plottype == "TreeNet Single Plot":
        dpvname=coord[1]["@Name"]
        predname=coord[0]["@Name"]
        predtype=datatype[predname]
        dpvtype=datatype[dpvname]
        data=plot["Data"]
        datalines=data.splitlines()
        values = []
        for line in datalines:
          values.append(line.split(","))
        for row in range(nrecords):
          for col in range(ncoord):
            name = coord[col]["@Name"]
            interp = coord[col]["@Interpretation"]
            if interp == "PartialDependence" or datatype[name] == "float":
              values[row][col]=float(values[row][col])
            valmat=np.array(values)
        pred=valmat[ : , 0]
        part_dep=valmat[ : , 1]
        actual=valmat[ : , 2]
        fig=plt.figure()
        if optype[predname] == "continuous":
          plt.plot(pred, part_dep)
        else:
          plt.bar(pred, part_dep, tick_label=cat[predname])
        plt.title("TreeNet Partial Dependency Plot")
        plt.xlabel(predname)
        plt.ylabel("Partial Dependency")
        self.display_figure(fig)

  def do_execute_direct(self, code, silent=False):
    """Execute the code in the subprocess.
    """
    self.payload = []
    wrapper = self.wrapper
    child = wrapper.child
    varimp = False
    global __echo__
    translate = False
    auto_summary = False

    if self._first:
      self._first = False
      self.handle_plot_settings()

    #We must have a carat prompt, so the ECHO command needs special processing
    if re.match("(?i)^ *EC", code):
      words = code.upper().split()
      if words[1] == "ON":
        __echo__ = True
      elif words[1] == "OFF":
        __echo__ = False
      code = "rem " + code
    elif re.match("(?i)^ *SUB", code):
      code += "\necho on"
    elif re.match("(?i)^ *\$VARIMP", code):
      tmpfile = tempfile.NamedTemporaryFile(delete=False)
      tmpname = tmpfile.name
      tmpfile.close()
      code = "translate language=pmml output='"+tmpname+"'"
      varimp = True
    elif re.match("(?i)^ *TRA", code):
      translate = True
    elif re.match("(?i)^ *\$AUTOSUM", code):
      auto_summary = True
      tmpfile = tempfile.NamedTemporaryFile(delete=False)
      tmpname = tmpfile.name
      tmpfile.close()
      code = "translate language=classic output='"+tmpname+"'"

    if not code.strip():
      self.kernel_resp = {
          'status': 'ok',
          'execution_count': self.execution_count,
          'payload': [],
          'user_expressions': {},
      }
      return

    interrupted = False
    output = ''
    if varimp or translate or auto_summary or not __echo__:
        stream_handler = None
    else:
      stream_handler = self.Print if not silent else None
    try:
      output = wrapper.run_command(code.rstrip(), timeout=None,
                                   stream_handler=stream_handler,
                                   stdin_handler=self.raw_input)
    except KeyboardInterrupt as e:
      interrupted = True
      output = wrapper.interrupt()
    except EOF:
      self.Print(child.before)
      self.do_shutdown(True)
      return

    if interrupted:
      self.kernel_resp = {
          'status': 'abort',
          'execution_count': self.execution_count,
      }

    exitcode, trace = self.check_exitcode()

    if exitcode:
      self.kernel_resp = {
          'status': 'error',
          'execution_count': self.execution_count,
          'ename': '', 'evalue': str(exitcode),
          'traceback': trace,
      }
    else:
      self.kernel_resp = {
          'status': 'ok',
          'execution_count': self.execution_count,
          'payload': [],
          'user_expressions': {},
      }

    if varimp:
      if "*ERROR*" not in output:
        with open(tmpname) as fd:
          doc = xmltodict.parse(fd.read(), disable_entities= False)
        self.display_varimp(doc)
        output = ""
      os.remove(tmpname)
    elif auto_summary:
      if "*ERROR*" not in output:
        with open(tmpname) as fd:
          trans = fd.read()
        if self.display_table(trans, "Automate Summary$"):
          output = ""
        else:
          output = "Automate summary table not present.  Did you run an AUTOMATE?"
      os.remove(tmpname)
    elif translate and len(output) > 0:
      try:
        if "SPMPlots" in output:
          doc = xmltodict.parse(self.extract(output, "<SPMPlots", "</SPMPlots>"),
                                disable_entities= False)
          self.SPMPlots(doc)
          output = ""
      except xml.parsers.expat.ExpatError:
        doc = {}
    if __echo__ and output:
      if stream_handler:
        stream_handler(output)
      else:
        return TextOutput(output)

  def handle_plot_settings(self):
    """Handle the current plot settings"""
    settings = self.plot_settings
    if ('format' not in settings or not settings['format']):
      settings['format'] = 'svg'
    self.inline_plotting = settings['backend'] == 'inline'
