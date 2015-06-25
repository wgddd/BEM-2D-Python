# -*- coding: utf-8 -*-
"""Module for flow field functions that include all swimmers."""
import numpy as np
from functions_general import panel_vectors, transformation, archive

def quilt(Swimmers, RHO, DEL_T, i):
    """Constructs the influence coefficient matrices and solves using Kutta condition.

    Args:
        Swimmers: List of Swimmer objects being simulated.
        RHO: Fluid density.
        DEL_T: Time step length.
        i: Time step number.
    """
    n_b = 0 # n_b is really a constant, only needs to be calculated once
    n_e = 0 # also a constant
    n_w = 0
    for Swim in Swimmers:
        Swim.i_b = n_b
        Swim.i_e = n_e
        Swim.i_w = n_w
        n_b += Swim.Body.N
        n_e += Swim.Edge.N
        n_w += Swim.Wake.get_relevant(i)[0]

    xp1 = np.empty((n_b,n_b))
    xp2 = np.empty((n_b,n_b))
    zp = np.empty((n_b,n_b))
    sigma_all = np.empty(n_b)
    for SwimI in Swimmers: # Influencing Swimmer (rows)
        (r0, rn) = (SwimI.i_b, SwimI.i_b+SwimI.Body.N) # Insertion row range
        sigma_all[r0:rn] = SwimI.Body.sigma[:]
        for SwimT in Swimmers: # Target Swimmer (columns)
            (c0, cn) = (SwimT.i_b, SwimT.i_b+SwimT.Body.N) # Insertion column range
            (xp1[r0:rn, c0:cn], xp2[r0:rn, c0:cn], zp[r0:rn, c0:cn]) = \
                transformation(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col, SwimI.Body.AF.x, SwimI.Body.AF.z)
    # Body source singularities influencing the bodies
    # Transpose so that row elements represent the effect on the (row number)th panel
    b_s = np.transpose((xp1 * np.log(xp1**2 + zp**2) - xp2 * np.log(xp2**2 + zp**2) \
                              + 2*zp*(np.arctan2(zp,xp2) - np.arctan2(zp,xp1)))/(4*np.pi))
    # Body doublet singularities influencing bodies themselves
    # Transpose similar to phi_s
    a = np.transpose(-(np.arctan2(zp,xp2) - np.arctan2(zp,xp1))/(2*np.pi))

    xp1 = np.empty((n_e,n_b))
    xp2 = np.empty((n_e,n_b))
    zp = np.empty((n_e,n_b))
    for SwimI in Swimmers:
        (r0, rn) = (SwimI.i_e, SwimI.i_e+SwimI.Edge.N)
#        r0 = SwimI.i_e
        for SwimT in Swimmers:
            (c0, cn) = (SwimT.i_b, SwimT.i_b+SwimT.Body.N)
            (xp1[r0:rn, c0:cn], xp2[r0:rn, c0:cn], zp[r0:rn, c0:cn]) = \
                transformation(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col, SwimI.Edge.x[:], SwimI.Edge.z[:])
    # Edge doublet singularities influencing the bodies
    b_de = np.transpose(-(np.arctan2(zp,xp2) - np.arctan2(zp,xp1))/(2*np.pi))

    # SOLVING TIME
    n_iter = 0
    while True:
        n_iter += 1

        if n_iter == 1:
            # Begin with explicit Kutta condition as first guess
            # Construct the augmented body matrix by combining body and trailing edge panel arrays
            c = np.zeros((n_b,n_b))
            for SwimI in Swimmers:
                c[:,SwimI.i_b] = -b_de[:, SwimI.i_e]
                c[:,SwimI.i_b+SwimI.Body.N-1] = b_de[:, SwimI.i_e]
            a_inv = np.linalg.inv(a + c)
            # Get right-hand side
            b = -np.dot(b_s, sigma_all) - np.dot(b_de[:, SwimI.i_e+1], Swim.Edge.mu[1])
            # Solve for bodies' doublet strengths using explicit Kutta
            mu_b_all = np.dot(a_inv, b)
            # First mu_guess (from explicit Kutta)
            for Swim in Swimmers:
                Swim.mu_guess = np.empty(2) # [0] is current guess, [1] is previous
                Swim.delta_cp = np.empty(2) # [0] is current delta_cp, [1] is previous
                Swim.Body.mu[:] = mu_b_all[Swim.i_b:Swim.i_b+Swim.Body.N]
                Swim.mu_guess[0] = Swim.Body.mu[-1]-Swim.Body.mu[0]

        else:
            if n_iter == 2: # Make a second initial guess
                # Update phi_dinv so it no longer includes explicit Kutta condition
                a_inv = np.linalg.inv(a)

                Swimmers[0].mu_guess[1] = Swimmers[0].mu_guess[0]
                Swimmers[0].delta_cp[1] = Swimmers[0].delta_cp[0]
                Swimmers[0].mu_guess[0] = 0.8*Swimmers[0].mu_guess[1] # Multiply first (explicit) guess by arbitrary constant to get second guess

            else: # Newton method to get delta_cp == 0
                # Get slope, which is change in delta_cp divided by change in mu_guess
                slope = (Swimmers[0].delta_cp[0]-Swimmers[0].delta_cp[1])/(Swimmers[0].mu_guess[0]-Swimmers[0].mu_guess[1])
                Swimmers[0].mu_guess[1] = Swimmers[0].mu_guess[0]
                Swimmers[0].delta_cp[1] = Swimmers[0].delta_cp[0]
                Swimmers[0].mu_guess[0] = Swimmers[0].mu_guess[1] - Swimmers[0].delta_cp[0]/slope

            # Form right-hand side including mu_guess as an influence
            rhs = -np.dot(b_s, sigma_all) - np.squeeze(np.dot(b_de, Swimmers[0].mu_guess[0]))

            Swimmers[0].Body.mu = np.dot(a_inv, rhs)

        for Swim in Swimmers:
            Swim.Body.pressure(RHO, DEL_T, i)
        if len(Swimmers) > 1 or Swimmers[0].SW_KUTTA == 0:
            break
        Swimmers[0].delta_cp[0] = np.absolute(Swimmers[0].Body.cp[-1]-Swimmers[0].Body.cp[0])
        if Swimmers[0].delta_cp[0] < 0.0001 or n_iter >= 1000:
#        if Swimmers[0].delta_cp[0] < 0.0001:
            break

    for Swim in Swimmers:
        # mu_past used in differencing for pressure
        Swim.Body.mu_past[1,:] = Swim.Body.mu_past[0,:]
        Swim.Body.mu_past[0,:] = Swim.Body.mu

        Swim.Edge.mu[0] = Swim.mu_guess[0]
        if i>1:
            Swim.Wake.alpha[0] = Swim.Edge.mu[1] - Swim.Edge.mu[0]

        Swim.Edge.gamma[0] = -Swim.Edge.mu[0]
        Swim.Edge.gamma[1] = Swim.Edge.mu[0]

        # Get gamma of body panels for use in wake rollup
        Swim.Body.gamma[0] = -Swim.Body.mu[0]
        Swim.Body.gamma[1:-1] = Swim.Body.mu[:-1]-Swim.Body.mu[1:]
        Swim.Body.gamma[-1] = Swim.Body.mu[-1]

def wake_rollup(Swimmers, DEL_T, i):
    """Performs wake rollup on the swimmers' wake panels.

    Args:
        Swimmers: List of Swimmer objects being simulated.
        DEL_T: Time step length.
        i: Time step number.
    """
    # Wake panels initialize when i==1
    if i == 0:
        pass

    else:
        for SwimT in Swimmers:
            # Number & starting index of targets (wake panel points/vortex particles that are rolling up)
            (NT, i_0) = SwimT.Wake.get_relevant(i)
            i_n = i_0 + NT
            SwimT.Wake.vx = np.zeros(NT)
            SwimT.Wake.vz = np.zeros(NT)
            DELTA_CORE = SwimT.DELTA_CORE
            for SwimI in Swimmers:
                # Coordinate transformation for body panels influencing wake
                (xp1, xp2, zp) = transformation(SwimT.Wake.x[i_0:i_n], SwimT.Wake.z[i_0:i_n], SwimI.Body.AF.x, SwimI.Body.AF.z)

                # Angle of normal vector with respect to global z-axis
                (nx, nz) = panel_vectors(SwimI.Body.AF.x, SwimI.Body.AF.z)[2:4]
                beta = np.arctan2(-nx, nz)

                # Katz-Plotkin eqns 10.20 and 10.21 for body source influence
                dummy1 = np.transpose(np.log((xp1**2+zp**2)/(xp2**2+zp**2))/(4*np.pi))
                dummy2 = np.transpose((np.arctan2(zp,xp2)-np.arctan2(zp,xp1))/(2*np.pi))

                # Rotate back to global coordinates
                dummy3 = dummy1*np.cos(beta) - dummy2*np.sin(beta)
                dummy4 = dummy1*np.sin(beta) + dummy2*np.cos(beta)

                # Finish eqns 10.20 and 10.21 for induced velocity by multiplying with sigma
                SwimT.Wake.vx += np.dot(dummy3, SwimI.Body.sigma)
                SwimT.Wake.vz += np.dot(dummy4, SwimI.Body.sigma)

                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
                NI = SwimI.Body.N+1
                xp = np.repeat(SwimT.Wake.x[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Body.AF.x[:,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Wake.z[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Body.AF.z[:,np.newaxis], NT, 1)

                # Find distance r_b between each influence/target
                r_b = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for body doublet (represented as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_b**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_b**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Body.gamma, add to induced velocity
                SwimT.Wake.vx += np.dot(dummy1, SwimI.Body.gamma)
                SwimT.Wake.vz += np.dot(dummy2, SwimI.Body.gamma)

                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
                NI = 1
                xp = np.repeat(SwimT.Wake.x[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Edge.x[:,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Wake.z[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Edge.z[:,np.newaxis], NT, 1)

                # Find distance r_e between each influence/target
                r_e = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for edge (as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_e**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_e**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Edge.gamma, add to induced velocity
                SwimT.Wake.vx += np.dot(dummy1, SwimI.Edge.gamma)
                SwimT.Wake.vz += np.dot(dummy2, SwimI.Edge.gamma)

#                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
#                if SwimI.Wake.SW_WAKE == 0:
#                    NI = SwimI.Wake.get_relevant(i)[0]+1
#                elif SwimI.Wake.SW_WAKE == 1:
#                    NI = SwimI.Wake.get_relevant(i)[0]
#                xp = np.repeat(SwimT.Wake.x[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.x[:NI,np.newaxis], NT, 1)
#                zp = np.repeat(SwimT.Wake.z[i_0:i_n,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.z[:NI,np.newaxis], NT, 1)
#
#                # Find distance r_w between each influence/target
#                r_w = np.sqrt(xp**2+zp**2)
#
#                # Katz-Plotkin eqns 10.9 and 10.10 for wake (as point vortices) influence
#                dummy1 = np.transpose(zp/(2*np.pi*(r_w**2+DELTA_CORE**2)))
#                dummy2 = np.transpose(-xp/(2*np.pi*(r_w**2+DELTA_CORE**2)))
#
#                # Finish eqns 10.9 and 10.10 by multiplying with Wake.gamma, add to induced velocity
#                if SwimI.Wake.SW_WAKE == 0:
#                    SwimT.Wake.vx += np.dot(dummy1, SwimI.Wake.gamma[:NI])
#                    SwimT.Wake.vz += np.dot(dummy2, SwimI.Wake.gamma[:NI])
#                elif SwimI.Wake.SW_WAKE == 1:
#                    SwimT.Wake.vx += np.dot(dummy1, SwimI.Wake.alpha[:NI])
#                    SwimT.Wake.vz += np.dot(dummy2, SwimI.Wake.alpha[:NI])

        for Swim in Swimmers:
            (NT, i_0) = SwimT.Wake.get_relevant(i)
            i_n = i_0 + NT
            # Modify wake with the total induced velocity
            Swim.Wake.u_psi = np.zeros((NT,2))
            u_psi(Swimmers, i, 'Wake')
            Swim.Wake.x[i_0:i_n] += (Swim.Wake.vx+Swim.Wake.u_psi[:,0])*DEL_T
            Swim.Wake.z[i_0:i_n] += (Swim.Wake.vz+Swim.Wake.u_psi[:,1])*DEL_T

def calc_psi(xt, zt, xi, zi, alpha, DELTA_CORE):
    """Computes the vector potential induced by a series of vortex particles.

    Args:
        xt, zt: Coordinates of target points where potential is measured.
        xi, zi: Coordinates of vortex influences.
        alpha: Strengths of the vortex influences.
    Returns:
        psi: Vector potential at each of the target points.
    """
    delta_x = np.repeat(xt[:,np.newaxis], len(xi), 1) - np.repeat(xi[:,np.newaxis].T, len(xt), 0)
    delta_z = np.repeat(zt[:,np.newaxis], len(zi), 1) - np.repeat(zi[:,np.newaxis].T, len(zt), 0)
    r = np.sqrt(delta_x**2 + delta_z**2 + DELTA_CORE**2)

#    matrix = 1./(4*np.pi*(r+DELTA_CORE))
    matrix = 1./(4*np.pi*r)
    return np.dot(matrix, alpha)

def u_psi(Swimmers, i, target='Body'):
    """Computes the velocity on body panels induced by wake particles."""
    DSTEP = 10**-5
    if i<= 1:
        pass
    elif target == 'Body':
        for SwimT in Swimmers:
            SwimT.Body.u_psi = np.zeros((SwimT.Body.N,2))
            for SwimI in Swimmers:
                NI = SwimI.Wake.get_relevant(i)[0]
                xi = np.insert(SwimI.Wake.x[:NI], 0, SwimI.Edge.x[-1])
                zi = np.insert(SwimI.Wake.z[:NI], 0, SwimI.Edge.z[-1])
                ai = np.insert(SwimI.Wake.alpha[:NI], 0, SwimI.Edge.mu[-1])

#                psi_xplus = calc_psi(SwimT.Body.AF.x_col+DSTEP, SwimT.Body.AF.z_col, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_xminus = calc_psi(SwimT.Body.AF.x_col-DSTEP, SwimT.Body.AF.z_col, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_zplus = calc_psi(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col+DSTEP, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_zminus = calc_psi(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col-DSTEP, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
                psi_xplus = calc_psi(SwimT.Body.AF.x_col+DSTEP, SwimT.Body.AF.z_col, xi, zi, ai, SwimI.DELTA_CORE)
                psi_xminus = calc_psi(SwimT.Body.AF.x_col-DSTEP, SwimT.Body.AF.z_col, xi, zi, ai, SwimI.DELTA_CORE)
                psi_zplus = calc_psi(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col+DSTEP, xi, zi, ai, SwimI.DELTA_CORE)
                psi_zminus = calc_psi(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col-DSTEP, xi, zi, ai, SwimI.DELTA_CORE)

                SwimT.Body.u_psi[:,0] += (psi_zminus-psi_zplus)/(2*DSTEP)
                SwimT.Body.u_psi[:,1] += (psi_xplus-psi_xminus)/(2*DSTEP)

    elif target == 'Wake':
        for SwimT in Swimmers:
            NT = SwimT.Wake.get_relevant(i)[0]
            SwimT.Wake.u_psi = np.zeros((NT,2))
            for SwimI in Swimmers:
                NI = SwimI.Wake.get_relevant(i)[0]
                xi = np.insert(SwimI.Wake.x[:NI], 0, SwimI.Edge.x[-1])
                zi = np.insert(SwimI.Wake.z[:NI], 0, SwimI.Edge.z[-1])
                ai = np.insert(SwimI.Wake.alpha[:NI], 0, SwimI.Edge.mu[-1])

#                psi_xplus = calc_psi(SwimT.Wake.x[:NT]+DSTEP, SwimT.Wake.z[:NT], SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_xminus = calc_psi(SwimT.Wake.x[:NT]-DSTEP, SwimT.Wake.z[:NT], SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_zplus = calc_psi(SwimT.Wake.x[:NT], SwimT.Wake.z[:NT]+DSTEP, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
#                psi_zminus = calc_psi(SwimT.Wake.x[:NT], SwimT.Wake.z[:NT]-DSTEP, SwimI.Wake.x[:NI], SwimI.Wake.z[:NI], SwimI.Wake.alpha[:NI], SwimI.DELTA_CORE)
                psi_xplus = calc_psi(SwimT.Wake.x[:NT]+DSTEP, SwimT.Wake.z[:NT], xi, zi, ai, SwimI.DELTA_CORE)
                psi_xminus = calc_psi(SwimT.Wake.x[:NT]-DSTEP, SwimT.Wake.z[:NT], xi, zi, ai, SwimI.DELTA_CORE)
                psi_zplus = calc_psi(SwimT.Wake.x[:NT], SwimT.Wake.z[:NT]+DSTEP, xi, zi, ai, SwimI.DELTA_CORE)
                psi_zminus = calc_psi(SwimT.Wake.x[:NT], SwimT.Wake.z[:NT]-DSTEP, xi, zi, ai, SwimI.DELTA_CORE)

                SwimT.Wake.u_psi[:,0] += (psi_zminus-psi_zplus)/(2*DSTEP)
                SwimT.Wake.u_psi[:,1] += (psi_xplus-psi_xminus)/(2*DSTEP)

def ou_psi(Swimmers, i):
    """Computes the velocity on body panels induced by wake particles."""
    if i <= 1:
        pass
    else:
        for SwimT in Swimmers:
            NT = SwimT.Body.N
            SwimT.Body.u_psi = np.zeros((SwimT.Body.N,2))
            for SwimI in Swimmers:
                DELTA_CORE = SwimI.DELTA_CORE
                NI = SwimI.Wake.get_relevant(i)[0]

                xp = np.repeat(SwimT.Body.AF.x_col[:,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.x[:NI,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Body.AF.z_col[:,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.z[:NI,np.newaxis], NT, 1)

                # Find distance r_w between each influence/target
                r_w = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for wake (as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_w**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_w**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Wake.gamma, add to induced velocity
                SwimT.Body.u_psi[:,0] += np.dot(dummy1, SwimI.Wake.alpha[:NI])
                SwimT.Body.u_psi[:,1] += np.dot(dummy2, SwimI.Wake.alpha[:NI])

def oquilt(Swimmers, RHO, DEL_T, i):
    """Constructs the influence coefficient matrices and solves using Kutta condition.

    Args:
        Swimmers: List of Swimmer objects being simulated.
        RHO: Fluid density.
        DEL_T: Time step length.
        i: Time step number.
    """
    n_b = 0 # n_b is really a constant, only needs to be calculated once
    n_e = 0 # also a constant
    n_w = 0
    for Swim in Swimmers:
        Swim.i_b = n_b
        Swim.i_e = n_e
        Swim.i_w = n_w
        n_b += Swim.Body.N
        n_e += Swim.Edge.N
        n_w += Swim.Wake.get_relevant(i)[0]

    xp1 = np.empty((n_b,n_b))
    xp2 = np.empty((n_b,n_b))
    zp = np.empty((n_b,n_b))
    sigma_all = np.empty(n_b)
    for SwimI in Swimmers: # Influencing Swimmer (rows)
        (r0, rn) = (SwimI.i_b, SwimI.i_b+SwimI.Body.N) # Insertion row range
        sigma_all[r0:rn] = SwimI.Body.sigma[:]
        for SwimT in Swimmers: # Target Swimmer (columns)
            (c0, cn) = (SwimT.i_b, SwimT.i_b+SwimT.Body.N) # Insertion column range
            (xp1[r0:rn, c0:cn], xp2[r0:rn, c0:cn], zp[r0:rn, c0:cn]) = \
                transformation(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col, SwimI.Body.AF.x, SwimI.Body.AF.z)
    # Body source singularities influencing the bodies
    # Transpose so that row elements represent the effect on the (row number)th panel
    b_s = np.transpose((xp1 * np.log(xp1**2 + zp**2) - xp2 * np.log(xp2**2 + zp**2) \
                              + 2*zp*(np.arctan2(zp,xp2) - np.arctan2(zp,xp1)))/(4*np.pi))
    # Body doublet singularities influencing bodies themselves
    # Transpose similar to phi_s
    a = np.transpose(-(np.arctan2(zp,xp2) - np.arctan2(zp,xp1))/(2*np.pi))

    xp1 = np.empty((n_e,n_b))
    xp2 = np.empty((n_e,n_b))
    zp = np.empty((n_e,n_b))
    for SwimI in Swimmers:
        r0 = SwimI.i_e
        for SwimT in Swimmers:
            (c0, cn) = (SwimT.i_b, SwimT.i_b+SwimT.Body.N)
            (xp1[r0, c0:cn], xp2[r0, c0:cn], zp[r0, c0:cn]) = \
                transformation(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col, SwimI.Edge.x, SwimI.Edge.z)
    # Edge doublet singularities influencing the bodies
    b_de = np.transpose(-(np.arctan2(zp,xp2) - np.arctan2(zp,xp1))/(2*np.pi))

    if i > 0: # There are no wake panels until i==1
        xp1 = np.empty((n_w,n_b))
        xp2 = np.empty((n_w,n_b))
        zp = np.empty((n_w,n_b))
        mu_w_all = np.empty(n_w)
        for SwimI in Swimmers:
            (r0, rn) = (SwimI.i_w, SwimI.i_w+i)
            mu_w_all[r0:rn] = SwimI.Wake.mu[:i]
            for SwimT in Swimmers:
                (c0, cn) = (SwimT.i_b, SwimT.i_b+SwimT.Body.N)
                (xp1[r0:rn, c0:cn], xp2[r0:rn, c0:cn], zp[r0:rn, c0:cn]) = \
                    transformation(SwimT.Body.AF.x_col, SwimT.Body.AF.z_col, SwimI.Wake.x[:i+1], SwimI.Wake.z[:i+1])
        # Wake doublet singularities influencing the bodies
        b_dw = np.transpose(-(np.arctan2(zp,xp2) - np.arctan2(zp,xp1))/(2*np.pi))

    # SOLVING TIME
    n_iter = 0
    while True:
        n_iter += 1

        if n_iter == 1:
            # Begin with explicit Kutta condition as first guess
            # Construct the augmented body matrix by combining body and trailing edge panel arrays
            c = np.zeros((n_b,n_b))
            for SwimI in Swimmers:
                c[:,SwimI.i_b] = -b_de[:, SwimI.i_e]
                c[:,SwimI.i_b+SwimI.Body.N-1] = b_de[:, SwimI.i_e]
            a_inv = np.linalg.inv(a + c)
            # Get right-hand side
            if i == 0:
                b = -np.dot(b_s, sigma_all)
            else:
                b = -np.dot(b_s, sigma_all) - np.dot(b_dw, mu_w_all)
            # Solve for bodies' doublet strengths using explicit Kutta
            mu_b_all = np.dot(a_inv, b)
            # First mu_guess (from explicit Kutta)
            for Swim in Swimmers:
                Swim.mu_guess = np.empty(2) # [0] is current guess, [1] is previous
                Swim.delta_cp = np.empty(2) # [0] is current delta_cp, [1] is previous
                Swim.Body.mu[:] = mu_b_all[Swim.i_b:Swim.i_b+Swim.Body.N]
                Swim.mu_guess[0] = Swim.Body.mu[-1]-Swim.Body.mu[0]

        else:
            if n_iter == 2: # Make a second initial guess
                # Update phi_dinv so it no longer includes explicit Kutta condition
                a_inv = np.linalg.inv(a)

                Swimmers[0].mu_guess[1] = Swimmers[0].mu_guess[0]
                Swimmers[0].delta_cp[1] = Swimmers[0].delta_cp[0]
                Swimmers[0].mu_guess[0] = 0.8*Swimmers[0].mu_guess[1] # Multiply first (explicit) guess by arbitrary constant to get second guess

            else: # Newton method to get delta_cp == 0
                # Get slope, which is change in delta_cp divided by change in mu_guess
                slope = (Swimmers[0].delta_cp[0]-Swimmers[0].delta_cp[1])/(Swimmers[0].mu_guess[0]-Swimmers[0].mu_guess[1])
                Swimmers[0].mu_guess[1] = Swimmers[0].mu_guess[0]
                Swimmers[0].delta_cp[1] = Swimmers[0].delta_cp[0]
                Swimmers[0].mu_guess[0] = Swimmers[0].mu_guess[1] - Swimmers[0].delta_cp[0]/slope

            # Form right-hand side including mu_guess as an influence
            if i == 0:
                rhs = -np.dot(b_s, sigma_all) - np.squeeze(np.dot(b_de, Swimmers[0].mu_guess[0]))
            else:
                rhs = -np.dot(b_s, sigma_all) - np.dot(np.insert(b_dw, 0, b_de[:,0], axis=1), np.insert(Swimmers[0].Wake.mu[:i], 0, Swimmers[0].mu_guess[0]))

            Swimmers[0].Body.mu = np.dot(a_inv, rhs)

        for Swim in Swimmers:
            Swim.Body.pressure(RHO, DEL_T, i)
        if len(Swimmers) > 1 or Swimmers[0].SW_KUTTA == 0:
            break
        Swimmers[0].delta_cp[0] = np.absolute(Swimmers[0].Body.cp[-1]-Swimmers[0].Body.cp[0])
        if Swimmers[0].delta_cp[0] < 0.0001 or n_iter >= 1000:
#        if Swimmers[0].delta_cp[0] < 0.0001:
            break

    for Swim in Swimmers:
        # mu_past used in differencing for pressure
        Swim.Body.mu_past[1,:] = Swim.Body.mu_past[0,:]
        Swim.Body.mu_past[0,:] = Swim.Body.mu

        Swim.Edge.mu = Swim.mu_guess[0]
        Swim.Edge.gamma[0] = -Swim.Edge.mu
        Swim.Edge.gamma[1] = Swim.Edge.mu

        # Get gamma of body panels for use in wake rollup
        Swim.Body.gamma[0] = -Swim.Body.mu[0]
        Swim.Body.gamma[1:-1] = Swim.Body.mu[:-1]-Swim.Body.mu[1:]
        Swim.Body.gamma[-1] = Swim.Body.mu[-1]

def owake_rollup(Swimmers, DEL_T, i):
    """Performs wake rollup on the swimmers' wake panels.

    Args:
        Swimmers: List of Swimmer objects being simulated.
        DEL_T: Time step length.
        i: Time step number.
    """
    # Wake panels initialize when i==1
    if i == 0:
        pass

    else:
        NT = i # Number of targets (wake panel points that are rolling up)
        for SwimT in Swimmers:
            SwimT.Wake.vx = np.zeros(NT)
            SwimT.Wake.vz = np.zeros(NT)
            DELTA_CORE = SwimT.DELTA_CORE
            for SwimI in Swimmers:
                # Coordinate transformation for body panels influencing wake
                (xp1, xp2, zp) = transformation(SwimT.Wake.x[1:i+1], SwimT.Wake.z[1:i+1], SwimI.Body.AF.x, SwimI.Body.AF.z)

                # Angle of normal vector with respect to global z-axis
                (nx, nz) = panel_vectors(SwimI.Body.AF.x, SwimI.Body.AF.z)[2:4]
                beta = np.arctan2(-nx, nz)

                # Katz-Plotkin eqns 10.20 and 10.21 for body source influence
                dummy1 = np.transpose(np.log((xp1**2+zp**2)/(xp2**2+zp**2))/(4*np.pi))
                dummy2 = np.transpose((np.arctan2(zp,xp2)-np.arctan2(zp,xp1))/(2*np.pi))

                # Rotate back to global coordinates
                dummy3 = dummy1*np.cos(beta) - dummy2*np.sin(beta)
                dummy4 = dummy1*np.sin(beta) + dummy2*np.cos(beta)

                # Finish eqns 10.20 and 10.21 for induced velocity by multiplying with sigma
                SwimT.Wake.vx += np.dot(dummy3, SwimI.Body.sigma)
                SwimT.Wake.vz += np.dot(dummy4, SwimI.Body.sigma)

                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
                NI = SwimI.Body.N+1
                xp = np.repeat(SwimT.Wake.x[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Body.AF.x[:,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Wake.z[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Body.AF.z[:,np.newaxis], NT, 1)

                # Find distance r_b between each influence/target
                r_b = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for body doublet (represented as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_b**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_b**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Body.gamma, add to induced velocity
                SwimT.Wake.vx += np.dot(dummy1, SwimI.Body.gamma)
                SwimT.Wake.vz += np.dot(dummy2, SwimI.Body.gamma)

                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
                NI = SwimI.Edge.N+1
                xp = np.repeat(SwimT.Wake.x[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Edge.x[:,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Wake.z[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Edge.z[:,np.newaxis], NT, 1)

                # Find distance r_e between each influence/target
                r_e = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for edge (as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_e**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_e**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Edge.gamma, add to induced velocity
                SwimT.Wake.vx += np.dot(dummy1, SwimI.Edge.gamma)
                SwimT.Wake.vz += np.dot(dummy2, SwimI.Edge.gamma)

                # Formation of (x-x0) and (z-z0) matrices, similar to xp1/xp2/zp but coordinate transformation is not necessary
                NI = i+1
                xp = np.repeat(SwimT.Wake.x[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.x[:i+1,np.newaxis], NT, 1)
                zp = np.repeat(SwimT.Wake.z[1:i+1,np.newaxis].T, NI, 0) - np.repeat(SwimI.Wake.z[:i+1,np.newaxis], NT, 1)

                # Find distance r_w between each influence/target
                r_w = np.sqrt(xp**2+zp**2)

                # Katz-Plotkin eqns 10.9 and 10.10 for wake (as point vortices) influence
                dummy1 = np.transpose(zp/(2*np.pi*(r_w**2+DELTA_CORE**2)))
                dummy2 = np.transpose(-xp/(2*np.pi*(r_w**2+DELTA_CORE**2)))

                # Finish eqns 10.9 and 10.10 by multiplying with Wake.gamma, add to induced velocity
                SwimT.Wake.vx += np.dot(dummy1, SwimI.Wake.gamma[:i+1])
                SwimT.Wake.vz += np.dot(dummy2, SwimI.Wake.gamma[:i+1])

        for Swim in Swimmers:
            # Modify wake with the total induced velocity
            Swim.Wake.x[1:i+1] += Swim.Wake.vx*DEL_T
            Swim.Wake.z[1:i+1] += Swim.Wake.vz*DEL_T