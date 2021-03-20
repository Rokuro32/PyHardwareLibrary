import time
import numpy as np
from struct import *
import csv

import usb.core
import usb.util

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from matplotlib.widgets import Button, TextBox

from typing import NamedTuple

class Status(NamedTuple):
    """
    Status of the Ocean Insight spectrometer. NamedTuple are compatible
    with regular tuples but allow access with names instead of indexes,
    simplifying usage.
    
    Attributes
    ----------
    pixels : int
        number of pixels on the sensors
    integrationTime: int
        integration time in milliseconds
    isLampEnabled : bool
        lamp strobe (connected on specific pin) is enabled
    triggerMode : int
        trigger mode: normal (freerunning, software or external)
    isSpectrumRequested: bool
        A spectrum is currently being acquired and prepared for transfer.
    timerSwap: bool
        Use an 8-bit timer or 16-bit timer
    isSpectralDataReady : bool
        The spectrum requested is ready to be transferred.
    """
    pixels : int = None
    integrationTime: int = None
    isLampEnabled : bool = None
    triggerMode : int = None    
    isSpectrumRequested: bool = None
    timerSwap: bool = None
    isSpectralDataReady : bool = None

class USB2000:
    """
    A USB2000 spectrometer.  This allows complete access to the hardware
    with simple functions to get the spectrum, or modify the integration time.
    
    Access to the device is done with pyusb and does not require any additional
    information. The USB-specific attributes of the USB2000 are available, 
    but are not needed for standard usage.  If you need to implement additional
    functions and communicate with the device (not all capabilities are currently
    coded), then you could implement them in a separate function.

    Methods starting with "get" and "set" will actually communication with the
    spectrometer and correspond to a command as defined in the OEM
    manual "USB2000 Data Sheet".

    Attributes
    ----------
    idVendor: int
        USB idVendor for OceanInsight (0x2457)

    idProduct: int
        USB idProduct for USB2000 (0x1002)

    wavelength: np.array(float)
        The wavelength corresponding to each pixel, as obtained from 
        factory calibration

    device : Device
        The USB device as obtained from pyusb core.find()

    configuration: Configuration
        The active USB configuration

    interface: Interface
        The active USB interface from the configuration

    epCommandOut: EndPoint
        The USB endpoint (i.e. the USB communication channel) to send commands

    epMainIn: EndPoint
        The USB endpoint (i.e. the USB communication channel) to receive replies
        for most commands

    epSecondaryIn: EndPoint
        The USB endpoint (i.e. the USB communication channel) to receive replies
        for spectral data and other commands

    """
    idVendor = 0x2457
    idProduct = 0x1002
    def __init__(self):
        """
        Finds and initialize the communication with the USB2000 spectrometer
        if there is one connected.

        If two are connected, it will pick one randomly.
        """
        self.device = usb.core.find(idVendor=self.idVendor, 
                                    idProduct=self.idProduct)        

        if self.device is None:
            raise RuntimeError('Device not found')

        self.device.set_configuration()
        self.configuration = self.device.get_active_configuration()
        self.interface = self.configuration[(0,0)]

        self.epCommandOut = self.interface[0]
        self.epMainIn = self.interface[1]
        self.epSecondaryIn = self.interface[3]

        self.initializeDevice()

    def initializeDevice(self):
        """
        Initialize the Spectrometer and obtain calibration information.
        This commands needs to be sent only once per session as soon as 
        the communication is started.
        """

        self.epCommandOut.write(b'0x01')
        self.getCalibration()

    def shutdownDevice(self):
        """
        Shutdown the Spectrometer. Currently does not perform anything.
        """
        return

    def setIntegrationTime(self, timeInMs):
        """ Set the integration time in an integer value of milliseconds 
        for a spectrum. If the value is smaller than 3 ms, it will be unchanged.
        """
        hi = timeInMs // 256
        lo = timeInMs % 256        
        self.epCommandOut.write([0x02, lo, hi])

    def getIntegrationTime(self):
        """ Get the integration time in as an integer value in milliseconds
        """
        status = self.getStatus()
        return status.integrationTime

    def getSerialNumber(self):
        """ Get the serial nunmber of the spectrometer.  This can be used to
        differentiate two connected spectrometers.
        """
        return self.getParameter(index=0)

    def getCalibration(self):
        """ Get the hardcoded calibration from the spectrometer.  It is a
        3rd-order polynomial. Currently, no nonlinearities are considered.
        """
        self.a0 = float(self.getParameter(index=1))
        self.a1 = float(self.getParameter(index=2))
        self.a2 = float(self.getParameter(index=3))
        self.a3 = float(self.getParameter(index=4))
        status = self.getStatus()
        self.wavelength = [ self.a0 + self.a1*x + self.a2*x*x + self.a3*x*x*x 
                            for x in range(status.pixels)]

    def getParameter(self, index):
        """ Get any of the 20 parameters hardcoded into the spectrometer.

        Parameters
        ----------

        index: int
            0 – Serial Number
            1 – 0th order Wavelength Calibration Coefficient 
            2 – 1st order Wavelength Calibration Coefficient
            3 – 2nd order Wavelength Calibration Coefficient 
            4 – 3rd order Wavelength Calibration Coefficient 
            5 – Stray light constant
            6 – 0th order non-linearity correction coefficient
            7 – 1st order non-linearity correction coefficient
            8 – 2nd order non-linearity correction coefficient
            9 – 3rd order non-linearity correction coefficient
            10 – 4th order non-linearity correction coefficient
            11 – 5th order non-linearity correction coefficient
            12 – 6th order non-linearity correction coefficient
            13 – 7th order non-linearity correction coefficient
            14 – Polynomial order of non-linearity calibration
            15 – Optical bench configuration: gg fff sss gg – Grating #, fff – filter wavelength, sss – slit size 
            16 - USB2000 configuration: AWL V
                A – Array coating Mfg, 
                W – Array wavelength (VIS, UV, OFLV), 
                L – L2 lens installed, 
                V – CPLD Version
            17 – Reserved
            18 – Reserved
            19 – Reserved

        Returns
        -------
        parameter : str 
            The value of the parameter as an ASCII string
        """
        self.epCommandOut.write([0x05, index])        
        parameters = self.epSecondaryIn.read(size_or_buffer=17, timeout=5000)
        return bytes(parameters[2:]).decode().rstrip('\x00')

    def requestSpectrum(self):
        """ Requests a spectrum.  The command will not return until the 
        spectrometer acknowledges that it did receive the request and flags
        it properly in its operating status. If after 1 second the request 
        has not been processed, it will raise a TimeoutError exception. """

        self.epCommandOut.write(b'\x09')
        timeOut = time.time() + 1
        while not self.isSpectrumRequested():
            time.sleep(0.001)
            if time.time() > timeOut:
                raise TimeoutError()

    def isSpectrumRequested(self) -> bool:
        """ The spectrometer is currently waiting for an acquisition to 
        complete and will raise the ready flag when the spectrum is ready
        to be retrieved.

        Returns
        -------
        isSpectrumRequested : bool 
            Whether or not the spectrometer is waiting for an acquisition 
        """
        status = self.getStatus()
        return status.isSpectrumRequested

    def isSpectrumReady(self):
        """ The requested spectrum is ready to be retrieved with getSpectrumData.

        Returns
        -------
        isSpectrumReady : bool 
            Whether or not the spectrum ready to be retrieved
        """
        status = self.getStatus()
        return status.isSpectralDataReady

    def getStatus(self):
        """ The status of the spectrometer returned as a Status named tuple.

        Returns
        -------
        status : Status 
            You can access the fields of the status by index (i.e. status[0]) or
            via their names. See the `Status` class.

            pixels : int = None
            integrationTime: int = None
            isLampEnabled : bool = None
            triggerMode : int = None    
            isSpectrumRequested: bool = None
            timerSwap: bool = None
            isSpectralDataReady : bool = None
       
        """
        self.epCommandOut.write(b'\xfe')
        status = self.epSecondaryIn.read(size_or_buffer=16, timeout=1000)
        statusList = unpack('>hh?B???xxxxxxx',status)
        return Status(*statusList)

    def getSpectrumData(self):
        """ Retrieve the spectral data.  You must call requestSpectrum first.
        If the spectrum is not ready yet, it will simply wait. The timeout 
        is set short so it may timeout.  You would normally check with
        isSpectrumReady before calling this function.

        Returns
        -------
        spectrum : np.array(float)
            The spectrum, in 16-bit integers corresponding to each wavelength
            available in self.wavelength.
        """
        spectrum = []
        for packet in range(32):
            bytesReadLow = self.epMainIn.read(size_or_buffer=64, timeout=200)
            bytesReadHi = self.epMainIn.read(size_or_buffer=64, timeout=200)
            
            spectrum.extend(np.array(bytesReadLow)+256*np.array(bytesReadHi))

        confirmation = self.epMainIn.read(size_or_buffer=1, timeout=200)
        spectrum[0] = spectrum[1]

        assert(confirmation[0] == 0x69)
        return np.array(spectrum)

    def getSpectrum(self, integrationTime=None):
        """ Obtain a spectrum from the spectrometer. This implies:
        1- changing the integration time if needed.
        2- requesting a spectrum,
        3- waiting until ready, then 
        4- actually retrieving and returning the data.
        
        Parameters
        ----------
        integrationTime: int, default None 
            integration time in milliseconds if not the currently configured
            time.

        Returns
        -------

        spectrum : np.array(float)
            The spectrum, in 16-bit integers corresponding to each wavelength
            available in self.wavelength.
        """
        if integrationTime is not None:
            self.setIntegrationTime(integrationTime)

        self.requestSpectrum()
        timeOut = time.time() + 1
        while not self.isSpectrumReady():
            time.sleep(0.001)
            if time.time() > timeOut:
                raise TimeoutError("Data never ready")

        return self.getSpectrumData()

    def saveSpectrum(self, filepath, spectrum=None):
        """ Save a spectrum to disk as a comma-separated variable file.
        If no spectrum is provided, request one from the spectrometer withoout
        changing the integration time.

        Parameters
        ----------

        filepath: str
            The path and the filename where to save the data.  If no path
            is included, the file is saved in the current directory 
            with the python script was invoked.

        spectrum: array_like
            A spectrum previously acquired or None to reuqest a spectrum

        """

        try:
            if spectrum is None:
                spectrum = self.getSpectrum()

            with open(filepath, 'w', newline='\n') as csvfile:
                fileWrite = csv.writer(csvfile, delimiter=',')
                fileWrite.writerow(['Wavelength [nm]','Intensity [arb.u]'])
                for x,y in list(zip(self.wavelength, spectrum)):
                    fileWrite.writerow(["{0:.2f}".format(x),y])
        except:
            print("Unable to save data.")

    def display(self):
        """ Display the spectrum with the SpectraViewer class."""
        viewer = SpectraViewer(spectrometer=self)
        viewer.display()

class SpectraViewer:
    def __init__(self, spectrometer):
        """ A matplotlib-based window to display and manage a spectrometer
        to replace the insanely inept OceanView software from OceanInsight.
        If anybody reads this from Ocean Insight, you can take direct people
        to this Python script.  It is simpler to call it directly from the
        spectrometer object with its own display function that will instantiate
        a SpectraViewer and call its display function with itself as a paramater.

        Parameters
        ----------

        spectrometer: USB2000
            A spectrometer from Ocean Insight.
        """

        self.spectrometer = spectrometer
        self.lastSpectrum = []
        self.figure = None
        self.axes = None
        self.quitFlag = False
        self.saveBtn = None
        self.integrationTimeBox = None
        self.animation = None

    def display(self):
        """ Display the spectrum in free-running mode, with simple
        autoscale, save and quit buttons as well as a text entry for
        the integration time. This is the only user-facing function that 
        is needed.
        """
        self.figure, self.axes = self.createFigure()

        axScale = plt.axes([0.12, 0.90, 0.15, 0.075])
        axSave = plt.axes([0.7, 0.90, 0.1, 0.075])
        axQuit = plt.axes([0.81, 0.90, 0.1, 0.075])
        axTime = plt.axes([0.59, 0.90, 0.1, 0.075])
        self.saveBtn = Button(axSave, 'Save')
        self.saveBtn.on_clicked(self.clickSave)
        quitBtn = Button(axQuit, 'Quit')
        quitBtn.on_clicked(self.clickQuit)
        autoscaleBtn = Button(axScale, 'Autoscale')
        autoscaleBtn.on_clicked(self.clickAutoscale)

        currentIntegrationTime = self.spectrometer.getIntegrationTime()
        self.integrationTimeBox = TextBox(axTime, 'Integration time [ms]',
                                          initial="{0}".format(currentIntegrationTime),
                                          label_pad=0.1)
        self.integrationTimeBox.on_submit(self.submitTime)
        self.figure.canvas.mpl_connect('key_press_event', self.keyPress)

        self.quitFlag = False
        self.animation = animation.FuncAnimation(self.figure, self.animate, interval=25)
        plt.show()

    def createFigure(self):
        """ Create matplotlib figure with decent properties. """

        SMALL_SIZE = 14
        MEDIUM_SIZE = 18
        BIGGER_SIZE = 36

        plt.rc('font', size=SMALL_SIZE)  # controls default text sizes
        plt.rc('axes', titlesize=SMALL_SIZE)  # fontsize of the axes title
        plt.rc('axes', labelsize=MEDIUM_SIZE)  # fontsize of the x and y labels
        plt.rc('xtick', labelsize=MEDIUM_SIZE)  # fontsize of the tick labels
        plt.rc('ytick', labelsize=MEDIUM_SIZE)  # fontsize of the tick labels
        plt.rc('legend', fontsize=SMALL_SIZE)  # legend fontsize
        plt.rc('figure', titlesize=BIGGER_SIZE)  # fontsize of the figure title

        fig, axes = plt.subplots()
        fig.set_size_inches(9, 6, forward=True)
        serialNumber = self.spectrometer.getSerialNumber()
        fig.canvas.set_window_title('Ocean Insight Spectrometer [serial # {0}, model USB2000]'.format(serialNumber))
        axes.set_xlabel("Wavelength [nm]")
        axes.set_ylabel("Intensity [arb.u]")
        return fig, axes

    def plotSpectrum(self, spectrum=None):
        """ Plot a spectrum into the figure or request a new spectrum. This
        is called repeatedly when the display function is called."""
        try:
            if spectrum is None:
                spectrum = self.spectrometer.getSpectrum()

            if len(self.axes.lines) == 0:
                self.axes.plot(self.spectrometer.wavelength, spectrum, 'k')
                self.axes.set_xlabel("Wavelength [nm]")
                self.axes.set_ylabel("Intensity [arb.u]")
            else: 
                self.axes.lines[0].set_data( self.spectrometer.wavelength, spectrum) # set plot data
                self.axes.relim()
        except:
            pass

    def animate(self, i):
        """ Internal function that is called repeatedly to manage the
        update  of the spectrum plot. It is better to use the `animation`
        strategy instead of a loop with  plt.pause() because plt.pause() will
        always bring the window to the  foreground. 

        This function is also responsible for determing if the user asked to quit. 
        """
        if self.quitFlag:
            self.animation.event_source.stop()
            self.animation = None
            plt.close()

        self.lastSpectrum = self.spectrometer.getSpectrum()
        self.plotSpectrum(spectrum=self.lastSpectrum)

    def keyPress(self, event):
        """ Event-handling function for keypress: if the user clicks command-Q
        on macOS, it will nicely quit."""

        if event.key == 'cmd+q':
            self.clickQuit(event)

    def submitTime(self, event):
        """ Event-handling function for when the user hits return/enter 
        in the integration time text field. The new integration time 
        is set in the spectrometer.

        We must autoscale the plot because the intensities could be very different.
        However, it takes a small amount of time for the spectrometer to react.
        We wait 0.3 seconds, which is small enough to need be annoying and seems to
        work fine.

        Anything incorrect will bring the integration time to 3 milliseconds.
        """
        try:
            time = int(self.integrationTimeBox.text)
            if time == 0:
                raise ValueError()
            self.spectrometer.setIntegrationTime(time)
            plt.pause(0.3)
            self.axes.autoscale_view()
        except:
            self.integrationTimeBox.set_val("3")

    def clickAutoscale(self, event):
        """ Event-handling function to autoscale the plot """
        self.axes.autoscale_view()

    def clickSave(self, event):
        """ Event-handling function to save the file.  We stop the animation
        to avoid acquiring more spectra. The last spectrum acquired (i.e.
        the one displayed) after we have requested the filename. 
        The data is saved as a CSV file, and the animation is restarted.
        
        Technical note: To request the filename, we use different strategies on 
        different platforms.  On macOS, we can use a function from the backend.
        On Windows and others, we fall back on Tk, which is usually installed 
        with python.
        """

        self.animation.event_source.stop()
        filepath = "spectrum.csv"
        try:
            filepath = matplotlib.backends.backend_macosx._macosx.choose_save_file('Save the data',filepath)
        except:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            filepath = filedialog.asksaveasfilename()

        if filepath is not None: 
            self.spectrometer.saveSpectrum(filepath, spectrum=self.lastSpectrum)

        self.animation.event_source.start()

    def clickQuit(self, event):
        """ Event-handling function to quit nicely."""

        self.quitFlag = True


if __name__ == "__main__":
    try:
        raise ValueError()
        spectrometer = USB2000()
        spectrometer.display()
    except Exception as err:
        """ Something unexpected occurred, which is probably a module not available.
        We provide some help.
        """
        print("""
    To use this `{0}` python script, you *must* have:

    1. PyUSB installed.
        This can be done with `pip install pyusb`.  On ome platforms,
        you also need to install libusb, a free package to access
        USB devices.  
        On Windows, you can leave the libusb.dll file
        directly in the same directory as this script.
    2. matplotlib installed
        If you want to use the display function, you need matplotlib.
        This can be installed with `pip install matplotlib`
    3. Tkinter installed.
        If you click "Save" in the window, you may need the Tkinter module.
        This comes standard with most python distributions.
    4. Obviously, a connected USB2000 spectrometer. It really needs to be 
        a USB2000 spectrometer.  The details of all the spectrometers
        are different (number of pixels, bits, wavelengths, speed, etc...)
        More spectrometers will be supported in the future.
            """.format(__file__)
            )
