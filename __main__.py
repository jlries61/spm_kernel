from ipykernel.kernelapp import IPKernelApp
from .kernel import SPMKernel
IPKernelApp.launch_instance(kernel_class=SPMKernel)
