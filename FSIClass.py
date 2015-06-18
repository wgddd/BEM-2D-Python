#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
BEM-2D
A 2D boundary element method code

"""
import numpy as np
from functions_general import panel_vectors
from scipy.interpolate import spline

class FSI(object):
    'Toolkit for Boundary Elelment Method Fluid Structure Interaction'
    def __init__(self, Body, Solid):
        """
        Iniitalizes object related variables needed for other class methods.
        
        Args:
            Body (object): A body object created from the swimmer class
            Solid (object): A solid object created from the solid class
        """
        self.fluidNodeDispl = np.zeros((Body.N+1, 2))
        self.fluidNodeDisplOld = np.zeros((Body.N+1, 2))
        self.solidNodeDispl = np.zeros((Body.N+1, 2))
        self.nodeDispl = np.zeros((Solid.Nelements+1, 2))
        self.nodeDisplOld = np.zeros((Solid.Nelements+1, 2))
        self.fsiResidual = np.zeros((Body.N+1, 2))
        self.fsiResidualOld = np.zeros((Body.N+1, 2))
        self.nodeResidual = np.zeros((Solid.Nelements+1, 2))
        self.nodeResidualOld = np.zeros((Solid.Nelements+1, 2))
        self.initialFsiResidualNorm = 0
        self.maxInitialFsiResidualNorm = 0
        self.fsiResidualNorm = 0
        self.maxFsiResidualNorm = 0
        self.maxMagFsiResidual = 0
        self.DU = np.zeros((Body.N+1,2))
        self.maxDU = 0
     
    def rotatePts(self, x0, y0, theta):
        """
        Rotates a pair of points a specified angle.
        
        Args:
            x0 (float): A NumPy array of x-coordinates to be rotated.
            y0 (float): A NumPy array of z-coordinates to be rotated.
            theta (float): Angle (in radians) to rotate coordinates.
            
        Returns:
            x (float): Rotated x-coordinate NumPy array theta radians from x0.
            y (float): Rotated y-coordinate NumPy array theta radians from y0.
        """
        x = x0 * np.cos(theta) - y0 * np.sin(theta)
        y = x0 * np.sin(theta) + y0 * np.cos(theta)
        return (x, y)
        
    def setInterfaceDisplacemet(self, outerCorr, couplingScheme):
        """
        Determines the relaxed solid/fluid body position based on a relaxation 
        factor and residual between solid and fluid domains.
        
        Args:
            outerCorr (int): Current FSI subiteration number.
            couplingScheme (str): The under-relaxation method used.
        """
        
        if (outerCorr < 3 or couplingScheme == 'FixedRelaxation'):
            # Use fixed-point relaxation
            self.fluidNodeDisplOld = np.copy(self.fluidNodeDispl)
            self.nodeDisplOld = np.copy(self.nodeDispl)
            self.fluidNodeDispl = self.fluidNodeDispl + self.fsiRelaxationFactor * self.fsiResidual
            self.nodeDispl = self.nodeDispl + self.fsiRelaxationFactor * self.nodeResidual
        elif (outerCorr >= 3 and couplingScheme == 'Aitken'):
            # Determine the new relaxation factor using the Aitken Method
            self.fsiRelaxationFactor = self.fsiRelaxationFactor * (np.dot(self.fsiResidualOld.T, (self.fsiResidualOld - self.fsiResidual))) / (np.linalg.norm(self.fsiResidualOld - self.fsiResidual, ord=2))**2
            self.fsiRelaxationFactor = np.linalg.norm(self.fsiRelaxationFactor, ord=2)
            if (self.fsiRelaxationFactor > 1.):
                self.fsiRelaxationFactor = 1           
            self.fluidNodeDisplOld = np.copy(self.fluidNodeDispl)
            self.nodeDisplOld = np.copy(self.nodeDispl)
            self.fluidNodeDispl = self.fluidNodeDispl + self.fsiRelaxationFactor * self.fsiResidual
            self.nodeDispl = self.nodeDispl + self.fsiRelaxationFactor * self.nodeResidual
        else:
            #TODO: Figure out how to throw an exception and hault exec.
            # Not sure how to make this throw an exception and hault exec.
            print 'ERROR! Invalid coupling scheme "%s"' % couplingScheme
            print 'Valid coupling schemes are:'
            print '    "Fixed Relaxation"'
            print '    "Aitken"'
                   
    def readFsiControls(self, fixedPtRelax, nOuterCorrMax):
        """
        Initializes FSI relaxation coupling variables.
        
        Args:
        fixedPtRelax (float): Fixed-point relaxation value for Newton iteration
        nOutCorrMax (int): Maximum allowed FSI coupling subiterations
        """
        self.fsiRelaxationFactorMin = fixedPtRelax
        self.fsiRelaxationFactor = np.copy(self.fsiRelaxationFactorMin)
        self.nOuterCorr = nOuterCorrMax
        
    def setInterfaceForce(self, Solid, Body, PyFEA, THETA, HEAVE, outerCorr, 
                          SW_VISC_DRAG, delFs, SW_INTERP_MTD, C, i_t):
        """
        Updates the structural mesh position, calculates the traction forces on
        the free nodes, and determines the initial condisitons for the timestep.
        
        Args:
            Solid (object): A solid object created from the solid class.
            Body (object): A body object created from the swimmer class.
            PyFEA (object): A FEA solver object created from the PyFEA class.
            t (float): Current simulation time.
            TSTEP (flaot): Small, incremental distance/time offsets.
            outerCorr (int): Current FSI subiteration number.
            SW_VISC_DRAG (bool): Used to determine 
                if viscous forces should be included.
            delFs (float): NumPy array of viscous force components.
            SW_INTERP_MTD (bool): Used to determine if linear or cubic spline 
                interpolation between fluid and solid domains should be used.
            C (float): Body chord length.
            i_t (int): Current time-step number.       
        """        
        # Superposing the structural displacements
        if (outerCorr > 1):
            Solid.nodes[:,0] += (self.nodeDispl[:,0] - self.nodeDisplOld[:,0])
            Solid.nodes[:,1] += (self.nodeDispl[:,1] - self.nodeDisplOld[:,1])         
            
        if (outerCorr <= 1):
            # Updating the new kinematics
            Solid.nodes[:,0] = (Solid.nodesNew[:,0] - Solid.nodesNew[0,0])*np.cos(THETA)
            Solid.nodes[:,1] = HEAVE + (Solid.nodesNew[:,0] - Solid.nodesNew[0,0])*np.sin(THETA)
            
            # Calculating the shift in node positions with the swimming velocity
            nodeDelxp = Body.AF.x_le * np.ones((Solid.Nelements + 1,1))
            nodeDelzp = Body.AF.z_le * np.ones((Solid.Nelements + 1,1))
            
            #Superposiing the kinematics and swimming translations
            Solid.nodes[:,0] = Solid.nodes[:,0] + nodeDelxp.T
            Solid.nodes[:,1] = Solid.nodes[:,1] + nodeDelzp.T          
            
        # Determine the load conditons from the fluid solver
        # Calculate the panel lengths and normal vectors
        (nx,nz,lp) = panel_vectors(Body.AF.x,Body.AF.z)[2:5]
        
        # Calculate the force magnitude acting on the panel due to pressure,
        # then calculate the x-z components of this force
        magPF = Body.p * lp * 1.
        pF = np.zeros((Body.N,2))
        if (SW_VISC_DRAG == 1):
            pF[:,0] = (magPF.T * nx.T * -1.) + delFs[:,0]
            pF[:,1] = (magPF.T * nz.T * -1.) + delFs[:,1]
        else:
            pF[:,0] = magPF.T * nx.T * -1.
            pF[:,1] = magPF.T * nz.T * -1.
        
        # Determine the moment arm between top and bottom panel points, and
        # collapse force and moments to the camber line
        colM = np.zeros((0.5*Body.N,1))
        colPF = np.zeros((0.5*Body.N,2))
        meanPt = np.zeros((0.5*Body.N,2))
        for i in xrange(int(0.5*Body.N)):
            meanPt[i,0] = 0.5*(Body.AF.x_mid[0,i] + Body.AF.x_mid[0,-(i+1)])
            meanPt[i,1] = 0.5*(Body.AF.z_mid[0,i] + Body.AF.z_mid[0,-(i+1)])
            colPF[i,:] = pF[i,:] + pF[-(i+1),:]
            colM[i,:] = -1. * pF[i,0] * (Body.AF.z_mid[0,i] - meanPt[i,1]) + \
                   pF[i,1] * (Body.AF.x_mid[0,i] - meanPt[i,0]) + \
                   -1. * pF[-(i+1),0] * (Body.AF.z_mid[0,-(i+1)] - meanPt[i,1]) + \
                   pF[-(i+1),1] * (Body.AF.x_mid[0,-(i+1)] - meanPt[i,0])
                   
        colPF = np.flipud(colPF)
        colM = np.flipud(colM)
        
        # Interpolate the collapsed forces and moments onto the structural mesh
        nodalInput = np.zeros((Solid.Nnodes,6))
        if (SW_INTERP_MTD == 1):
            nodalInput[:,0] = np.interp(Solid.nodes[:,2], Solid.meanline_c0[0.5*Body.N:], colPF[:,0], left=0, right=0)
            nodalInput[:,1] = np.interp(Solid.nodes[:,2], Solid.meanline_c0[0.5*Body.N:], colPF[:,1], left=0, right=0)
            nodalInput[:,5] = np.interp(Solid.nodes[:,2], Solid.meanline_c0[0.5*Body.N:], colM[:,0], left=0, right=0)
        else:
            nodalInput[:,0] = spline(Solid.meanline_c0[0.5*Body.N:], colPF[:,0], Solid.nodes[:,2])
            nodalInput[:,1] = spline(Solid.meanline_c0[0.5*Body.N:], colPF[:,1], Solid.nodes[:,2])
            nodalInput[:,5] = spline(Solid.meanline_c0[0.5*Body.N:], colM[:,0], Solid.nodes[:,2])
            
        # Rotate force components into the relative cooridnate system
        (nodalInput[:,0], nodalInput[:,1]) = self.rotatePts(nodalInput[:,0], nodalInput[:,1], -THETA)
        
        # Create the load matrix
        Fload = np.zeros((3*(Solid.Nnodes),1))
        Fload[0::3,0] = np.copy(nodalInput[:,0])
        Fload[1::3,0] = np.copy(nodalInput[:,1])
        Fload[2::3,0] = np.copy(nodalInput[:,5])
        
        # Create element area matrix
        A = np.copy(Solid.tBeamStruct[:,0])
        
        # Create area moment of inertia matrix
        I = 1. * Solid.tBeamStruct[:,0]**3 / 12
        
        # Initial element length
        l_0 = C / Solid.Nelements
        
        # Initial displacements and velocities
#        if (i_t <= 1 and outerCorr <= 1):
        temp = 3 * Solid.fixedCounter
        if (i_t <= 1 and outerCorr <= 1):
            PyFEA.U_n = np.zeros((3*Solid.Nnodes,1))
            PyFEA.Udot_n = np.zeros((3*Solid.Nnodes,1))
            PyFEA.UdotDot_n = np.zeros((3*Solid.Nnodes - temp,1))
            PyFEA.U_nPlus = np.zeros((3*Solid.Nnodes - temp,1))
            PyFEA.Udot_nPlus = np.zeros((3*Solid.Nnodes - temp,1))
            PyFEA.UdotDot_nPlus = np.zeros((3*Solid.Nnodes - temp,1))
        elif (i_t > 0 and outerCorr <= 1):
            PyFEA.U_n = np.zeros((3*Solid.Nnodes,1))
            PyFEA.Udot_n = np.zeros((3*Solid.Nnodes,1))
            PyFEA.U_n[temp:,0] = PyFEA.U_nPlus.T
            PyFEA.Udot_n[temp:,0] = PyFEA.Udot_nPlus.T
        
        PyFEA.Fload = np.copy(Fload)
        PyFEA.A = np.copy(A)
        PyFEA.I = np.copy(I)
        PyFEA.l = l_0 * np.ones(Solid.Nelements)
            
    def getDisplacements(self, Solid, Body, PyFEA, THETA, HEAVE, SW_INTERP_MTD, FLEX_RATIO):
        """
        Calculates the new position of the fluid body based on the displacements
        calculated by the structural body. This is used to calculate the FSI 
        coupling residual used in an interative strong coupling between the 
        fluid and solid solutions.
        
        Args:
            Solid (object): A solid object created from the solid class.
            Body (object): A body object created from the swimmer class.
            PyFEA (object): A FEA solver object created from the PyFEA class.
            t (float): Current simulation time.
            TSTEP (flaot): Small, incremental distance/time offsets.
            SW_INTERP_MTD (bool): Used to determine if linear or cubic spline 
                interpolation between fluid and solid domains should be used.
            FLEX_RATIO (float): Percent of the body to remain rigid as measured
                from the leading edge.
        """          
        # Get the absolute x and z displacements
        nodeDisplacements = np.zeros((Solid.Nnodes-Solid.fixedCounter,2))
        nodeDisplacements[:,1] =  np.copy(PyFEA.U_nPlus[1::3].T)
        nodeDisplacements[:,0] =  (Solid.nodes_0[Solid.fixedCounter:,1] + nodeDisplacements[:,1]) * np.sin(-PyFEA.U_nPlus[2::3].T) 
        
        # Calculate the new structural locations
        tempNodes = np.copy(Solid.nodes_0)
        tempNodes[Solid.fixedCounter:,0] = Solid.nodes_0[Solid.fixedCounter:,0] + nodeDisplacements[:,0] # New x-position
        tempNodes[Solid.fixedCounter:,1] = Solid.nodes_0[Solid.fixedCounter:,1] + nodeDisplacements[:,1] # New z-position
        
        # Transform the structural mesh into the fluid body absolute reference frame.
        tempNodes[:,0], tempNodes[:,1] = self.rotatePts(tempNodes[:,0], tempNodes[:,1], THETA)
        tempNodes[:,1] = tempNodes[:,1] + HEAVE
        
        # Calculating the shift in node positions with the swimming velocity
        nodeDelxp = Body.AF.x_le * np.ones((Solid.Nnodes,1))
        nodeDelzp = Body.AF.z_le * np.ones((Solid.Nnodes,1))

        # Shift the nodes with the swimming
        tempNodes[:,0] = tempNodes[:,0] + nodeDelxp.T
        tempNodes[:,1] = tempNodes[:,1] + nodeDelzp.T
        
        # Calculate the normal components of the structure elements
        normal = np.zeros((Solid.Nelements,2))
        for i in xrange(Solid.Nelements):
            normal[i,0] = -1 * (tempNodes[i+1,1] - tempNodes[i,1])
            normal[i,1] =  1 * (tempNodes[i+1,0] - tempNodes[i,0])
            normal[i,:] = normal[i,:] / np.sqrt(normal[i,0]**2 + normal[i,1]**2)
        
        # Initialize arrays for the structure top and bottom panel nodes
        topNodes = np.zeros((Solid.Nnodes, 3))
        bottomNodes = np.zeros((Solid.Nnodes, 3)) 
        
        # For each node of the strucutreal mesh, calculate the top and bottom 
        # surface position based on the element's thickness
        topNodes[:-1,0] = tempNodes[:-1,0] + 0.5 * Solid.tBeam[:,0] * normal[:,0]
        topNodes[:-1,1] = tempNodes[:-1,1] + 0.5 * Solid.tBeam[:,0] * normal[:,1]
        topNodes[-1,0:2] = np.copy(tempNodes[-1,0:2])
        topNodes[:,2] = np.copy(tempNodes[:,2])
        bottomNodes[:-1,0] = tempNodes[:-1,0] - 0.5 * Solid.tBeam[:,0] * normal[:,0]
        bottomNodes[:-1,1] = tempNodes[:-1,1] - 0.5 * Solid.tBeam[:,0] * normal[:,1]
        bottomNodes[-1,0:2] = np.copy(tempNodes[-1,0:2])
        bottomNodes[:,2] = np.copy(tempNodes[:,2])
        
        # Interpolate the structual top and bottom nodes to find the fluid 
        # panel node positions.
        i = np.rint(0.5 * np.shape(Solid.meanline_p0)[0])
        if (SW_INTERP_MTD == 1):
            bottomXp = np.interp(Solid.meanline_p0[0:i], bottomNodes[:,2], bottomNodes[:,0], left=True, right=True)
            bottomZp = np.interp(Solid.meanline_p0[0:i], bottomNodes[:,2], bottomNodes[:,1], left=True, right=True)
            topXp = np.interp(Solid.meanline_p0[i:], topNodes[:,2], topNodes[:,0], left=True, right=True)
            topZp = np.interp(Solid.meanline_p0[i:], topNodes[:,2], topNodes[:,1], left=True, right=True)
        else:
            bottomXp = spline(bottomNodes[:,2], bottomNodes[:,0], Solid.meanline_p0[0:i])      
            bottomZp = spline(bottomNodes[:,2], bottomNodes[:,1], Solid.meanline_p0[0:i])
            topXp = spline(topNodes[:,2], topNodes[:,0], Solid.meanline_p0[i:])
            topZp = spline(topNodes[:,2], topNodes[:,1], Solid.meanline_p0[i:])    
        
        # Build arrays containing the new fluid panel node positions.
        newxp = np.zeros_like(Solid.meanline_p0)
        newzp = np.zeros_like(Solid.meanline_p0)
        newxp[0:i] = np.copy(bottomXp)
        newxp[i:] = np.copy(topXp)
        newzp[0:i] = np.copy(bottomZp)
        newzp[i:] = np.copy(topZp)       
        
        # Replace the new fluid panel node positions with the rigid fluid panel
        # nodes if they were defined to be rigid.
        for i in xrange(Body.N):
            if (Solid.meanline_p0[i] <= FLEX_RATIO):
                newxp[i] = np.copy(Body.AF.x[i])
                newzp[i] = np.copy(Body.AF.z[i])
        
        # Store the absolute displacements and temporary nodes.
        self.DU[:,0] = newxp - Body.AF.x
        self.DU[:,1] = newzp - Body.AF.z
        self.maxDU = np.max(np.sqrt(self.DU[:,0]**2 + self.DU[:,1]**2))
        Solid.tempNodes = np.copy(tempNodes)
        
    def calcFSIResidual(self, Solid, outerCorr):
        """
        Calculates residuals between the fluid and solid domains. This is used 
        to judge convergence between the fluid and solid domains.
        
        Args:
            Solid (object): A solid object created from the solid class.
            outerCorr (int): Current FSI subiteration number.
        """
        # Get the caluclated solid domain displacements
        self.solidNodeDispl = np.copy(self.DU)
        
        # Store the previous FSI residual as the old residual value. This is
        # done for both the fluid and solid domains.
        self.fsiResidualOld = np.copy(self.fsiResidual)
        self.nodeResidualOld = np.copy(self.nodeResidual)
        
        # Calculate the residual between fluid and solid domains. This is done
        # for both the fluid body panels and the structure mesh.
        self.fsiResidual = self.solidNodeDispl - self.fluidNodeDispl    
        self.nodeResidual = (Solid.tempNodes[:,0:2]-Solid.nodes[:,0:2]) - self.nodeDispl
        
        # Calculate the FSI residual magnitude
        magFsiResidual = np.sqrt(self.fsiResidual[:,0]**2 + self.fsiResidual[:,1]**2)
        
        # Calculate the L2 norm of the FSI residual to represent the convergence 
        # as a single RMS value.
        self.fsiResidualNorm = np.linalg.norm(self.fsiResidual, ord=2)
        
        # Calculate the Infinity norm of the FSI residual to represent the 
        # convergence as a single maximum value.
        self.maxFsiResidualNorm = np.linalg.norm(self.fsiResidual, ord=np.inf)
        
        # If this is the first subiteration for the time-step, scale the L2 and
        # Infinity norms with these values. The scaled norm will always be 1 for
        # the first subiteration. Convergence between fluid and soild domains 
        # will be judged based on how many orders of magnitude these values drop 
        # with successive subiteration.
        if (outerCorr == 1 ):
            self.initialFsiResidualNorm = np.copy(self.fsiResidualNorm)
            self.maxInitialFsiResidualNorm = np.copy(self.maxFsiResidualNorm)
            
        # Scale the FSI residual norm based on the first subiteration's
        # FSI residual norm.
        self.fsiResidualNorm = self.fsiResidualNorm / self.initialFsiResidualNorm
        self.maxFsiResidualNorm = self.maxFsiResidualNorm / self.maxInitialFsiResidualNorm
        
        # Determine the maximum magnitude of the FSI residual.
        self.maxMagFsiResidual = np.max(magFsiResidual)