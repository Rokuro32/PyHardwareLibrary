from hardwarelibrary.physicaldevice import *
import numpy as np

class LinearMotionDevice(PhysicalDevice):

    def __init__(self, serialNumber:str, productId:np.uint32, vendorId:np.uint32):
        super().__init__(serialNumber, productId, vendorId)
        self.x = None
        self.y = None
        self.z = None
        self.nativeStepsPerMicrons = 1
        self.xMinLimit = None
        self.yMinLimit = None
        self.zMinLimit = None
        self.xMaxLimit = None
        self.yMaxLimit = None
        self.zMaxLimit = None

    def moveTo(self, position):
        self.doMoveTo(position)

    def moveBy(self, displacement):
        self.doMoveBy(displacement)

    def position(self) -> ():
        return self.doGetPosition()

    # def moveInMicronsTo(self, position):
    #     self.doMoveTo(position)

    # def moveInMicronsBy(self, displacement):
    #     self.doMoveBy(displacement)

    # def positionInMicrons(self) -> ():
    #     return self.doGetPosition()

class DebugLinearMotionDevice(LinearMotionDevice):

    def __init__(self):
        super().__init__("debug", 0xffff, 0xfffd)
        (self.x, self.y, self.z) = (0,0,0)

    def doGetPosition(self) -> (float, float, float):
        return (self.x, self.y, self.z)

    def doMoveTo(self, position):
        x, y, z = position
        (self.x, self.y, self.z) = (x,y,z)

    def doMoveBy(self, displacement):
        dx, dy, dz = displacement
        self.x += dx
        self.y += dy 
        self.z += dz

    def doInitializeDevice(self):
        pass

    def doShutdownDevice(self):
        pass