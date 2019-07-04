# Definition of the SPM kernel class SPMKernel
# Copyright (C) 2019 John L. Ries

# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This module is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this module.  If not, see <http://www.gnu.org/licenses/>.

import sys
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
from ordered_set import OrderedSet

from spm_kernel.version import __version__

# Useful constants
__SPM__ = 'spmu'   # SPM exec.  Eventually, we'll allow this to be set by the installer.
__prompt__ = ' >'  # The SPM carat prompt.
                   # We need this so that pexpect can find the end of the output.
__echo__ = True    # Send SPM console output to Jupyter.

# I'll confess that I copied this from gnuplot_kernel (my initial model)
# and don't know exactly what it does.
try:
  FileNotFoundError
except NameError:
  # Python 2
  FileNotFoundError = OSError

class SPMKernel(ProcessMetaKernel):
  implementation = 'SPM Kernel'
  implementation_version = __version__
  language = 'SPM'
  language_version = '8.0' # It probably works with older versions as well, but...
  language_info = {'name': 'SPM',
                   'codemirror_mode': 'shell',
                   'mimetype': 'text/plain',
                   'file_extension': '.cmd'}
  # The following is installed into Jupyter as SPM/kernel.json
  # The name element must be defined in order for the installer to work correctly
  kernel_json = {'name': 'SPM',
                 "argv": [sys.executable, "-m", "spm_kernel",
                          "-f", "{connection_file}"],
                 "display_name": "SPM",
                 "language": "SPM"}
  _first = True # We set this to false after do_execute_direct is executed for the first time.
  inline_plotting = True # I added this as an experiment.  It may not be necessary

  #All we're doing here is displaying the opening banner
  @property
  def banner(self):
    if self._banner is None:
      # The --L flag requests licensing information.
      self._banner = check_output([__SPM__, '--L']).decode('utf-8')
      return self._banner

  def __init__(self, *args, **kwargs):
    MetaKernel.__init__(self, *args, **kwargs)
    self.wrapper = None
    self.wrapper = self.makeWrapper()
    #self.log.setLevel(logging.DEBUG) # Uncomment to show debug writes

  # Start SPM session
  def makeWrapper(self):
    return REPLWrapper(__SPM__, __prompt__, None)

  # Extract specified XML/HTML element from input
  def extract(self, input, starttag, endtag):
    # input is a multiline text string.
    # starttag is the beginning of the starting tag
    #   (the opening "<" and the name are probably enough).
    # endtag is ending tag.
    start = input.index(starttag)
    finish = input.index(endtag)
    finlen = len(endtag)
    return input[start : finish + finlen]

  # Generic function to display a figure inside of Jupyter
  # Thanks to Steven Silvester for helping me to work this out
  def display_figure(self, fig):
    # The object of the game is to put the image into an HTML img element
    # and then send it to Jupyter for display.
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi='figure')
    width = fig.get_figwidth() * fig.dpi
    data = "<img src='data:image/png;base64,{0}' width={1}/>"
    data = data.format(b64encode(buf.getvalue()).decode('utf-8'), width)
    super(SPMKernel, self).Display(HTML(data))

  # Generic function to extract the specified SPM text table from input,
  # format it as an HTML table and display it inside of Jupyter.
  def display_table(self, input, pattern, nvar_show = 5):
    # input is a multiline text string containing SPM classic output,
    #   hopefully including the desired table.
    # pattern is the regular expression the table header needs to match.
    # nvar_show is the maximum number of variable names to display in a table cell
    #   If more are found, then only the number is given.
    found = False               # Set to True when table is found
    inline = input.splitlines() # Split input into an array of lines to facilitate parsing
    iline = 0                   # Line index
    nline = len(inline)         # Number of lines in input
    maxline = nline - 1         # Maximum line index

    # Locate and parse the table title.
    title = ""
    for line in inline:
      if re.search(pattern, line):
        if iline > 0 and re.search("^ =+$", inline[iline - 1]) and \
           re.search("^ =+$", inline[iline + 1]):
          title = line
          found = True
          break
      iline = iline + 1

    #Abort if we didn't find it.
    if not found:
      return found

    #Scan forward for dashed line separating the table header from the content
    for i in range(iline, maxline):
      if re.search("^ -+$", inline[i]):
        headline = inline[i - 1]
        iline = i + 1
        break

    # maxlen is the maximum line length detected thus far.
    # If it's zero, then we didn't find the table.
    maxlen = len(headline)
    if maxlen == 0:
      return False

    # Now we parse the table into an array
    table = []
    nlines = 0
    line = "" # We may have to concatenate multiple input lines
    for i in range(iline, maxline):
      # When we reach a blank line, then we've reached the end of the table
      if len(inline[i]) == 0:
        break
      # If the input line ends with a comma, concatenate to existing line.
      if len(line) == 0 or re.search(",$", line):
        line = line + inline[i]
      else: # Add the line we have to the array
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

    # Determine the starting and ending position of each column in the input table
    # Each line in SPM classic output ends with a blank space, which we can ignore.
    startcol = [1]
    endcol = []
    lastline = nlines # Last line of the table
    footline = nlines # This will be set to the first line of the footer, if there is one
    iline = 0         # Line index
    for line in table:
      icol = 0 # Column index
      if re.search("^ -+$", line): # We have found a footer for the table
        footline = iline
        break
      incol = False # Set to true when the content is non-blank
      for col in range(1, len(line)-1):
        if line[col] == " ":
          # A space following a comma separates names in a list.
          if incol and line[col-1] != ",":
            incol = False
            if icol >= len(startcol) - 1: # Add additional elements to our boundary arrays
              endcol.append(col)
              # This addresses a curious alignment issue.
              if col < len(headline) and headline[col] == " ":
                startcol.append(col+1) # Set startcol[icol] to the next position
              else:
                startcol.append(col) # Set startcol[icol] to the current position
            elif col > endcol[icol]: # We found text past the detected end of the column
              endcol[icol] = col # So adjust the end point of the column accordingly
            icol = icol + 1 # Increment the column indicator
        else: # We found text
          incol = True
      iline = iline + 1 # Increment the line indicator
    endcol.append(maxlen) # The end of the last column is at maxlen
    ncol = len(startcol)  # Number of columns in the table

    # Parse the table header into individual cells
    head = []
    for icol in range(ncol):
      head.append(headline[startcol[icol]:endcol[icol]])

    # Parse the table body into individual cells
    body = []
    for iline in range(footline):
      line = table[iline]
      cell=[]
      for icol in range(ncol):
        current_col = line[startcol[icol]:endcol[icol]]
        if ", " in current_col:
          varlist = current_col.rsplit(", ")
          nvar = len(varlist)
          if nvar > nvar_show:
            current_col = str(nvar) + " variables"
        cell.append(current_col)
      body.append(cell)

    # Parse the table footer, if any, into individual cells
    foot = []
    if nlines > footline:
      for iline in range(footline + 1, nlines):
        line = table[iline]
        cell = []
        for icol in range(ncol):
          cell.append(line[startcol[icol]:endcol[icol]])
        foot.append(cell)

    # Render the table into HTML
    html="<table>"
    if len(title) > 0:
      html = html + "<caption>" + title + "</caption>"
    html = html + "<thead><tr>"
    for header in head: # Column titles are bolded
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
        # We also bold the first cell in each row of the footer
        html = html + "<th>" + row[0] + "</th>"
        for icol in range(1, ncol):
          html = html + "<td>" + row[icol] + "</td>"
        html = html + "</tr>"
      html = html + "</tfoot>"
    html = html + "</table>"

    super(SPMKernel, self).Display(HTML(html)) # Display the table we just rendered
    return found

  # Display variable importances as a bar plot
  def display_varimp(self, doc):
    # doc is a dictionary containing PMML/Translate output as parsed by xmltodict.

    # Create an array of model outputs (more than one model may be documented)
    models = [];
    # If we're processing a battery, multiple instances of all three elements may be present
    for modtype in ("MiningModel", "TreeModel", "RegressionModel"):
      if modtype in doc["PMML"]:
        mod = doc["PMML"][modtype]
        if type(mod) is list:
          models.extend(mod)
        else:
          models.append(mod)

    # Extract and sum variable importances
    impsum = {} # Sums of importances
    nmod = 0 # Number of models processed
    for mod in models:
      if mod["@algorithmName"] in ("Logit", "Regress", "2SLS"):
        continue # We don't calculate variable importances for these model types
      nmod = nmod + 1                # Increment model type
      schema = mod["MiningSchema"]   # We extract the importances from the mining schema
      fields = schema["MiningField"] # List of field elements
      for field in fields:
        name = field["@name"]
        usageType = field["@usageType"]
        if usageType == "active": # "Active" fields are predictors
          if name not in impsum:
            impsum[name] = 0  # Add the field to impsum and initialize value to 0
          if "@importance" in field:
            impsum[name] = impsum[name] + 100*float(field["@importance"])
          else: # Bug: The importance of the most important predictor isn't always recorded.
            impsum[name] = impsum[name] + 100

    # Calculate average variable importances
    varimp = {}
    for name in impsum.keys():
      varimp[name]=impsum[name]/nmod

    # Sort predictors in descending order of importance
    varimp_series = pd.Series(varimp).sort_values(ascending=True)
    predname=varimp_series.keys()

    # Generate and display the plot (horizontal bar chart)
    fig = plt.figure()
    varimp_series.plot.barh(title="Variable Importances", color="blue")
    plt.xlabel("Importance")
    plt.ylabel("Predictor Name")
    self.display_figure(fig)

  # Generate and display partial dependency plots
  def SPMPlots(self,doc):
    # doc is the output from TRANSLATE LANGUAGE=PLOTS parsed into a dictionary by xmltodict.
    # For now, two way plots are ignored (we'll allow them to be displayed later)

    plots = doc["SPMPlots"]["Plot"]            # List of plots
    datadict=doc["SPMPlots"]["DataDictionary"] # Data dictionary
    datafields=datadict["DataField"]           # List of data fields
    datatype={}                                # Data type for each field
    optype={}                                  # Operating type for each field
    cat={}                                     # List of categories for each categorical field

    # Parse the data dictionary
    for datafield in datafields:
      datatype[datafield["@name"]]=datafield["@dataType"]
      optype[datafield["@name"]]=datafield["@optype"]
      if datafield["@optype"] == "categorical":
        cat[datafield["@name"]]=[]
        vallist=datafield["Value"]
        for value in vallist:
          cat[datafield["@name"]].append(value["@value"])

    # Parse and display the individual plots
    for plot in plots:
      plottype = plot["@Type"]             # Plot type
      modtype = plot["@Model"]             # Model type
      nrecords = int(plot["@NRecords"])    # Number of records
      ncoord = int(plot["@NCoordinates"])  # Number of coordinates
      coord = plot["Coordinate"]           # List of coordinates
      if plottype == "TreeNet Single Plot":
        dpvname = coord[1]["@Name"]          # Target variable name
        predname = coord[0]["@Name"]         # Predictor name
        predtype = datatype[predname]        # Predictor type
        dpvtype = datatype[dpvname]          # Target variable type
        data = plot["Data"]                  # Plot data
        datalines = data.splitlines()        # We split it into an array of lines
        nrecords = len(datalines)            # Number of records
        level = ""                           # Target class
        if optype[dpvname] == "categorical": # Categorical target
          level = coord[1]["@Level"]
        # Parse data lines into cells
        values = []
        for line in datalines:
          values.append(line.split(","))
        pred = []
        part_dep = []
        for row in range(nrecords):
          for col in range(ncoord):
            name = coord[col]["@Name"]
            interp = coord[col]["@Interpretation"]
            if (interp == "PartialDependence" or datatype[name] == "float") and \
               len(values[row][col]) > 0:
              values[row][col] = float(values[row][col])
            if values[row][col] == -1e+36: #SPM missing value code
              values[row][col] = np.NaN
          pred.append(values[row][0])     # Predictor values
          part_dep.append(values[row][1]) # Partial dependencies
        # Generate and display figure
        title = "TreeNet Partial Dependency Plot"
        if len(level) > 0:
          title = title + " (" + dpvname + " = " + level + ")"
        fig=plt.figure()
        if optype[predname] == "continuous": # We generate a line graph
          plt.plot(pred, part_dep)
        else: # We generate a bar chart
          plt.bar(pred, part_dep, tick_label=cat[predname])
        plt.title(title)
        plt.xlabel(predname)
        plt.ylabel("Partial Dependency")
        self.display_figure(fig)

  def display_sequence(self, input):
    # Plot performance stats for a model sequence
    # Currently, only TreeNet is supported
    modtype = ""
    output = ""
    timing_enabled = "Time/Tree" in input
    if "TreeNet Results" in input:
      modtype = "TreeNet"
    if len(modtype) > 0:
      line = input.splitlines() # Split input into lines
      nlines = len(line)        # Number of lines in input
      ntrees = []               # List of numbers of trees
      stat = {}                 # Dictionary of performance stats
      # Read input line by line
      for iline in range(nlines):
        if re.match("^ TreeNet Results$", line[iline]):
          perfstat = OrderedSet() # Set of performance stat types
          found = False
          # First, find the loss function line
          while iline < nlines and not found:
            found = re.match("^ Loss Function:", line[iline])
            iline = iline + 1
          while iline < nlines and len(line[iline]) == 0:
            iline = iline + 1
          if found:
            use_test_sample = "Train" not in line[iline]
            # Compile the list of performance stats to plot
            if use_test_sample:
              parts = re.sub("^ +", "", line[iline]).split()
              for part in parts:
                perfstat.add(re.sub("-","", part))
              iline = iline + 3
            else: # Exploratory model
              iline = iline + 1
              part = line[iline].split()
              lastind = 2
              if timing_enabled: # We have one more column to deal with
                lastind = lastind + 1
              for ipart in range(2, len(part) - lastind):
                name = part[ipart]
                if name != "Fract":
                  perfstat.add(part[ipart])
              iline = iline + 2
            # Now parse the model sequence table
            while iline < nlines and len(line[iline]) > 0:
              parts = re.sub("^ +", "", line[iline]).split()
              nt = int(parts.pop(0)) # Number of trees
              ntrees.append(nt)
              for name in perfstat:
                stat[(nt, name, "Learn")] = float(parts.pop(0))
                if use_test_sample:
                  stat[(nt, name, "Test")] = float(parts.pop(0))
              iline = iline + 1
        if re.match("^ Learn and Test Performance$", line[iline]) or \
           re.match("^ Model Performance$", line[iline]):
          for i in range(2):
            iline = iline + 1
            while not re.match("^ -+$", line[iline]):
              iline = iline + 1
          statname = line[iline-2].lstrip().split()
          sample = line[iline-1].lstrip().split()
          head1 = sample.pop(0)
          iline = iline + 1
          for i in range(len(sample)):
            if sample[i] == "Test/CV":
              sample[i] = "Test"
            if statname[i] == "Class.Error":
              if "Class" in perfstat:
                statname[i] = "Class"
              else:
                statname[i] = "CLASS"
          for name in statname:
            perfstat.add(name)
          while iline < nlines and len(line[iline]) > 0:
            parts = re.sub("^ +", "", line[iline]).split()
            nt = int(parts.pop(0)) # Number of trees
            for i in range(len(statname)):
              stat[(nt, statname[i], sample[i])] = float(parts[i])
            iline = iline + 1
      # Generate plots
      for name in perfstat:
        learn = []
        test = []
        ntrees2 = []
        for nt in ntrees:
          if (nt, name, "Learn") in stat:
            ntrees2.append(nt)
            learn.append(stat[(nt, name, "Learn")])
            if use_test_sample:
              test.append(stat[(nt, name, "Test")])
        fig = plt.figure()
        plt.plot(ntrees2, learn, label="Learn")
        if use_test_sample:
          plt.plot(ntrees2, test, label="Test")
        plt.title("Model Performance")
        plt.xlabel("# trees")
        plt.ylabel(name)
        plt.legend()
        self.display_figure(fig)
    return output

  def do_execute_direct(self, code, silent=False):
    """Execute the code in the subprocess.
    """
    self.payload = []
    wrapper = self.wrapper
    child = wrapper.child
    varimp = False        # Set to True if processing a $VARIMP statement
    global __echo__       # We're using the global version of __echo__
    translate = False     # Set to True if handling a translation
    auto_summary = False  # Set to True if processing an $AUTOSUM statement
    nvar_show = 5         # Maximum number of predictor variables to list for a given shave step
    sequence = False      # Set to True if generating a sequence report

    # Handle plot settings first time through
    if self._first:
      self._first = False
      self.handle_plot_settings()

    # We must have a carat prompt, so the ECHO command needs special processing
    if re.match("(?i)^ *EC", code):
      words = code.upper().split()
      if words[1] == "ON":
        __echo__ = True
      elif words[1] == "OFF":
        __echo__ = False
      code = "rem " + code
    elif re.match("(?i)^ *SUB", code): # We turn ECHO back on after a SUBMIT file runs
      code += "\necho on"
    elif re.match("(?i)^ *\$VARIMP", code): # Variable importances requested
      # We extract them from PMML/Translate output
      # We write to an output file to prevent the process from hanging if there is too much of it.
      tmpfile = tempfile.NamedTemporaryFile(delete=False)
      tmpname = tmpfile.name
      tmpfile.close()
      code = "translate language=pmml output='"+tmpname+"'"
      varimp = True
    elif re.match("(?i)^ *TRA", code): # TRANSLATE statement requires special handling
      translate = True
    elif re.match("(?i)^ *\$AUTOSUM", code): # AUTOMATE summary requested
      # We extract the table from Classic/Translate output for the convenience of the programmer.
      auto_summary = True
      tmpfile = tempfile.NamedTemporaryFile(delete=False)
      tmpname = tmpfile.name
      tmpfile.close()
      code = "translate language=classic output='"+tmpname+"'"
    elif re.match("(?i)^ *\$SEQUENCE", code): # Model sequence report requested
      sequence = True
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

    # Here, we process the statement(s)
    interrupted = False
    output = ''
    if varimp or translate or auto_summary or sequence or not __echo__:
        stream_handler = None
    else:
      stream_handler = self.Print if not silent else None
    try:
      # Booby Trap:
      # output is empty unless no stream handler is defined
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

    # Now that we have submitted the statement, some commands require special processing.
    if varimp: # Display variable importances
      # This requires us to parse PMML/Translate output
      if "*ERROR*" not in output:
        with open(tmpname) as fd:
          doc = xmltodict.parse(fd.read(), disable_entities= False)
        self.display_varimp(doc)
        output = ""
      os.remove(tmpname)
    elif auto_summary: # Display AUTOMATE summary table if there is one
      if "*ERROR*" not in output:
        with open(tmpname) as fd:
          trans = fd.read()
        if self.display_table(trans, "Automate Summary$", nvar_show = nvar_show):
          output = ""
        else:
          output = "Automate summary table not present.  Did you run an AUTOMATE?"
      os.remove(tmpname)
    elif sequence: # Generate and display sequence report, if appropriate
      if "*ERROR*" not in output:
        with open(tmpname) as fd:
          trans = fd.read()
          if self.display_table(trans, "Learn and Test Performance$"):
            pass
          elif self.display_table(trans, "Learn and Cross Validation Performance$"):
            pass
          elif self.display_table(trans, "Model Performance$"):
            pass
        output = self.display_sequence(trans)
      os.remove(tmpname)
    elif translate and len(output) > 0:
      try:
        if "SPMPlots" in output:
          # Display partial dependency plots
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
