from pulse_lib.base_pulse import pulselib
import numpy as np
import matplotlib.pyplot as plt

p = pulselib()

# add to pulse_lib
p.add_awgs('AWG1',None)
p.add_awgs('AWG2',None)
p.add_awgs('AWG3',None)
p.add_awgs('AWG4',None)

# define channels
awg_channels_to_physical_locations = dict({'B0':('AWG1', 1), 'P1':('AWG1', 2),
											'B1':('AWG1', 3), 'P2':('AWG1', 4),
											'B2':('AWG2', 1), 'P3':('AWG2', 2),
											'B3':('AWG2', 3), 'P4':('AWG2', 4),
											'B4':('AWG3', 1), 'P5':('AWG3', 2),
											'B5':('AWG3', 3), 'G1':('AWG3', 4),
											'I_MW1':('AWG4', 1), 'Q_MW1':('AWG4', 2),	
											'I_MW2':('AWG4', 3), 'Q_MW2':('AWG4', 4)})
	
p.define_channels(awg_channels_to_physical_locations)

# format : dict of channel name with delay in ns (can be posive/negative)
p.add_channel_delay({
	'I_MW1':50,
	'Q_MW1':50,
	# 'M1':20,
	# 'M2':-25,
	})

awg_virtual_gates = {
	'virtual_gates_names_virt' :
		['vP1','vP2','vP3','vP4','vP5','vB0','vB1','vB2','vB3','vB4','vB5'],
	'virtual_gates_names_real' :
		['P1','P2','P3','P4','P5','B0','B1','B2','B3','B4','B5'],
	'virtual_gate_matrix' :
		np.eye(11)
}
p.add_virtual_gates(awg_virtual_gates)

awg_IQ_channels = {
	'vIQ_channels' : ['qubit_1','qubit_2'],
	'rIQ_channels' : [['I_MW1','Q_MW1'],['I_MW2','Q_MW2']],
	'LO_freq' :[18.4e9, 19.65e9]
	# do not put the brackets for the MW source
	# e.g. MW_source.frequency
	}
	
p.add_IQ_virt_channels(awg_IQ_channels)
p.finish_init()


# importarant voltages
P1_unload_Q2 = -20
P2_unload_Q2 = -40

P1_hotspot = -40
P2_hotspot = -50

P1_load_init_Q2 = 0
P2_load_init_Q2 = 0

P1_operating_point =10
P2_operating_point =15

P1_detuning_pulse = -20
P2_detuning_pulse = -35

seg1  = p.mk_segment('INIT')

seg1.P1.add_block(0,1e6, P1_unload_Q2)
seg1.P2.add_block(0,1e6, P2_unload_Q2)
seg1.reset_time()
seg1.P1.add_block(0,100e3, P1_hotspot)
seg1.P2.add_block(0,100e3, P2_hotspot)
seg1.reset_time()
seg1.P2.add_block(0,3e6, P1_load_init_Q2)
seg1.P2.add_block(0,3e6, P2_load_init_Q2)

seg2  = p.mk_segment('MANIP')

#let's make a loop over the 4 possible input combinations
import pulse_lib.segments.looping as lp
phaseQ1 = lp.loop_obj()
phaseQ1.add_data([np.pi/2, np.pi/2, -np.pi/2, -np.pi/2], axis = 0, names = 'phases', units = 'Rad')
phaseQ2 = lp.loop_obj()
phaseQ2.add_data([np.pi/2, -np.pi/2, np.pi/2, -np.pi/2], axis = 0, names = 'phases', units = 'Rad')	


freq_1 = 18.4e9
freq_2 = 19.7e9

# define global voltage for the whole sequence (operating point voltages (we do not want to define them in every pulse))
seg2.P1 += P1_operating_point
seg2.P2 += P2_operating_point


# two microwave pulses
seg2.qubit_1.add_sin(0,225,freq_1 ,40, np.pi/4)
seg2.qubit_2.add_sin(0,225,freq_2 ,20, np.pi/4)
seg2.qubit_2.wait(5)
seg2.reset_time()

# cphase
seg2.P1.add_block(0, 90, P1_detuning_pulse)
seg2.P2.add_block(0, 90, P2_detuning_pulse)
seg2.P2.wait(5)
seg2.reset_time()

# add reference shifts for the microwave pulses
seg2.qubit_1.add_global_phase(phaseQ1)
seg2.qubit_2.add_global_phase(phaseQ2)

# two microwave pulses
seg2.qubit_1.add_sin(0,225,freq_1 ,40, np.pi/4)
seg2.qubit_2.add_sin(0,225,freq_2 ,20, np.pi/4)
seg2.qubit_2.wait(5)
seg2.reset_time()

# cphase
seg2.P1.add_block(0, 90, P1_detuning_pulse)
seg2.P2.add_block(0, 90, P2_detuning_pulse)
seg2.P2.wait(5)
seg2.reset_time()

# two microwave pulses
seg2.qubit_1.add_sin(0,225,freq_1 ,40, np.pi/4)
seg2.qubit_2.add_sin(0,225,freq_2 ,20, np.pi/4)
seg2.qubit_2.wait(5)
seg2.reset_time()


# plt.figure()
# seg2.I_MW1.plot_segment([0])
# seg2.Q_MW1.plot_segment([0])

# seg2.I_MW2.plot_segment([0])
# seg2.Q_MW2.plot_segment([0])

# plt.legend()

# plt.figure()
# seg2.I_MW1.plot_segment([1])
# seg2.Q_MW1.plot_segment([1])

# seg2.I_MW2.plot_segment([1])
# seg2.Q_MW2.plot_segment([1])

# plt.legend()

# plt.figure()
# seg2.I_MW1.plot_segment([2])
# seg2.Q_MW1.plot_segment([2])
# seg2.I_MW2.plot_segment([2])
# seg2.Q_MW2.plot_segment([2])
# plt.legend()

# plt.figure()
# seg2.I_MW1.plot_segment([3])
# seg2.Q_MW1.plot_segment([3])
# seg2.I_MW2.plot_segment([3])
# seg2.Q_MW2.plot_segment([3])
# plt.legend()

plt.figure()
seg1.P1.plot_segment()
seg1.P2.plot_segment()
plt.show()

seg3  = p.mk_segment('Readout')
