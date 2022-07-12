import logging
from numbers import Number
from copy import copy
from typing import Any, List, Dict, Callable
from dataclasses import dataclass

import numpy as np
from .rendering import render_custom_pulse

class SequenceBuilderBase:
    def __init__(self, name, sequencer):
        self.name = name
        self.seq = sequencer
        self.t_end = 0
        self.sinewaves = []
        self.t_next_marker = None
        self.imarker = 0
        self.max_output_voltage = sequencer.max_output_voltage

    def register_sinewave(self, waveform):
        try:
            index = self.sinewaves.index(waveform)
            waveid = f'sine{index}'
        except:
            index = len(self.sinewaves)
            self.sinewaves.append(waveform)
            waveid = f'sine{index}'
            data = waveform.render()
            self.seq.add_wave(waveid, data)
        return waveid

    def register_sinewave_iq(self, waveform):
        try:
            index = self.sinewaves.index(waveform)
            waveids = (f'iq{index}I', f'iq{index}Q')
        except:
            index = len(self.sinewaves)
            self.sinewaves.append(waveform)
            waveids = (f'iq{index}I', f'iq{index}Q')
            data = waveform.render_iq()
            self.seq.add_wave(waveids[0], data[0])
            self.seq.add_wave(waveids[1], data[1])
        return waveids

    def add_markers(self, markers):
        self.markers = markers
        self.imarker = -1
        self.set_next_marker()

    def set_next_marker(self):
        self.imarker += 1
        if len(self.markers) > self.imarker:
            self.t_next_marker = self.markers[self.imarker][0]
        else:
            self.t_next_marker = None

    def insert_markers(self, t):
        while self.t_next_marker is not None and t > self.t_next_marker:
            marker = self.markers[self.imarker]
            self._set_markers(marker[0], marker[1])
            self.set_next_marker()

    def _set_markers(self, t, value):
        self.seq.set_markers(value, t_offset=t)

    def _update_time(self, t, duration):
        if t < self.t_end:
            raise Exception(f'Overlapping pulses {t} > {self.t_end} ({self.name})')
        self.t_end = t + duration

    def _update_time_and_markers(self, t, duration):
        if t < self.t_end:
            raise Exception(f'Overlapping pulses {t} > {self.t_end} ({self.name})')
        self.insert_markers(t)
        self.t_end = t + duration

    def add_comment(self, comment):
        self.seq.add_comment(comment)

    def finalize(self):
        for i in range(self.imarker, len(self.markers)):
            marker = self.markers[i]
            self._set_markers(marker[0], marker[1])


class VoltageSequenceBuilder(SequenceBuilderBase):
    def __init__(self, name, sequencer, rc_time=None):
        super().__init__(name, sequencer)
        self.rc_time = rc_time
        self.integral = 0.0
        self.custom_pulses = []
        if rc_time is not None:
            self.compensation_factor = 1 / (1e9 * rc_time)
        else:
            self.compensation_factor = 0.0

    def ramp(self, t, duration, v_start, v_end):
        self._update_time_and_markers(t, duration)
        v_start_comp = self._compensate_bias_T(v_start)
        v_end_comp = self._compensate_bias_T(v_end)
        self.integral += duration * (v_start + v_end)/2
        self.seq.ramp(duration, v_start_comp, v_end_comp, t_offset=t, v_after=None)

    def set_offset(self, t, duration, v):
        # sequencer only updates offset, no continuing action: duration=0
        self._update_time_and_markers(t, 0)
        v_comp = self._compensate_bias_T(v)
        self.integral += duration * v
        if self.rc_time and duration > 0.01 * 1e9 * self.rc_time:
            self._update_time_and_markers(t, duration)
            v_end = self._compensate_bias_T(v)
            self.seq.ramp(duration, v_comp, v_end, t_offset=t, v_after=None)
        else:
            self.seq.set_offset(v_comp, t_offset=t)

    def pulse(self, t, duration, amplitude, waveform):
        self._update_time_and_markers(t, duration)
        # TODO @@@ add 2*np.pi*t*frequency*1e-9 to phase ??
        wave_id = self.register_sinewave(waveform)
        self.seq.shaped_pulse(wave_id, amplitude, t_offset=t)

    def custom_pulse(self, t, duration, amplitude, custom_pulse):
        self._update_time_and_markers(t, duration)
        wave_id = self.register_custom_pulse(custom_pulse, amplitude)
        self.seq.shaped_pulse(wave_id, 1.0, t_offset=t)

    def register_custom_pulse(self, custom_pulse, scaling):
        data = render_custom_pulse(custom_pulse, scaling)
        for index,wave in enumerate(self.custom_pulses):
            if np.all(wave == data):
                return f'pulse{index}'
        index = len(self.custom_pulses)
        waveid = f'pulse{index}'
        self.custom_pulses.append(data)
        self.seq.add_wave(waveid, data)
        return waveid


    def _compensate_bias_T(self, v):
        return v + self.integral * self.compensation_factor


class IQSequenceBuilder(SequenceBuilderBase):
    def __init__(self, name, sequencer, nco_frequency):
        super().__init__(name, sequencer)
        self.seq.nco_frequency = nco_frequency
        self.add_comment(f'IQ: NCO={nco_frequency/1e6:7.2f} MHz')

    def pulse(self, t, duration, amplitude, waveform):
        self._update_time_and_markers(t, duration)
        self.add_comment(f'MW pulse {waveform.frequency/1e6:6.2f} MHz {waveform.duration} ns')
        waveform = copy(waveform)
        waveform.frequency -= self.seq.nco_frequency

        if abs(waveform.frequency) > 1:
            wave_ids = self.register_sinewave_iq(waveform)
            self.seq.shaped_pulse(wave_ids[0], amplitude,
                                  wave_ids[1], amplitude,
                                  t_offset=t)
            # Adjust NCO after driving with other frequency
            delta_phase = 2*np.pi*waveform.frequency*duration*1e-9
            self.shift_phase(t+duration, delta_phase)

        elif not isinstance(waveform.phmod, Number):
            wave_ids = self.register_sinewave_iq(waveform)
            self.seq.shaped_pulse(wave_ids[0], amplitude,
                                  wave_ids[1], amplitude,
                                  t_offset=t)
        else:
            # frequency is less than 1 Hz make it 0.
            waveform.frequency = 0
            # phase is constant
            cycles = 2*np.pi*(waveform.phase + waveform.phmod)
            if isinstance(waveform.amod, Number):
                # TODO @@@ add option to use waveform for short pulses with 1 ns resolution
                ampI = amplitude * waveform.amod * np.sin(cycles)
                ampQ = amplitude * waveform.amod * np.cos(cycles)
                # generate block pulse
                self.seq.block_pulse(duration, ampI, ampQ, t_offset=t)
            else:
                # phase is accounted for in ampI, ampQ
                waveform.phase = np.pi*0.5 # TODO @@@ Why this phase???
                waveform.phmod = 0
                ampI = amplitude * np.sin(cycles)
                ampQ = amplitude * np.cos(cycles)
                # same wave for I and Q
                wave_id = self.register_sinewave(waveform)
                self.seq.shaped_pulse(wave_id, ampI, wave_id, ampQ, t_offset=t)

    def shift_phase(self, t, phase):
        '''
        Arguments:
            phase (float): phase in rad.
        '''
        self._update_time_and_markers(t, 0.0)
        # normalize phase to -1.0 .. + 1.0 for Q1Pulse sequencer
        norm_phase = (phase/np.pi + 1) % 2 - 1
        self.seq.shift_phase(norm_phase, t_offset=t)


@dataclass
class _SeqCommand:
    time: int
    func: Callable[..., Any]
    args: List[Any]
    kwargs: Dict[str,Any]

class AcquisitionSequenceBuilder(SequenceBuilderBase):
    def __init__(self, name, sequencer, n_repetitions, nco_frequency=None, rf_source=None):
        super().__init__(name, sequencer)
        self.n_repetitions = n_repetitions
        self.seq.nco_frequency = nco_frequency
        self.rf_source = rf_source
        self.n_triggers = 0
        self._integration_time = None
        self._data_scaling = None
        self._commands = []
        self.rf_source_mode = rf_source.mode if rf_source is not None else None
        self._pulse_end = -1
        if rf_source is not None:
            scaling = 1/(rf_source.attenuation * self.max_output_voltage*1000)
            self._rf_amplitude = rf_source.amplitude * scaling
            self._n_out_ch = 1 if isinstance(rf_source.output[1], int) else 2

    @property
    def integration_time(self):
        return self.seq.integration_length_acq

    @integration_time.setter
    def integration_time(self, value):
        if value is None:
            raise ValueError('integration time cannot be None')
        if self._integration_time is None:
            logging.info(f'{self.name}: integration time {value}')
            self._integration_time = value
            self.seq.integration_length_acq = value
        elif self._integration_time != value:
            raise Exception('Only 1 integration time (t_measure) per channel is supported')

    def add_markers(self, markers):
        for marker in markers:
            t,value = marker
            self._add_command(t,
                              self.seq.set_markers, value, t_offset=t)

    def acquire(self, t, t_integrate):
        self._update_time(t, t_integrate)
        self.integration_time = t_integrate
        self.n_triggers += 1
        self._add_scaling(1/t_integrate, 1)
        # enqueue: self.seq.acquire('default', 'increment', t_offset=t)
        self._add_command(t,
                          self.seq.acquire, 'default', 'increment', t_offset=t)
        if self.rf_source_mode in ['pulsed', 'shaped']:
            self._add_pulse(t, t_integrate)

    def repeated_acquire(self, t, t_integrate, n, t_period):
        duration = n * t_period
        self._update_time(t, duration)
        self.integration_time = t_integrate
        self.n_triggers += n
        self._add_scaling(1/t_integrate, n)
        # enqueue: self.seq.repeated_acquire(n, t_period, 'default', 'increment', t_offset=t)
        self._add_command(t,
                          self.seq.repeated_acquire, n, t_period, 'default', 'increment', t_offset=t)
        if self.rf_source_mode in ['pulsed', 'shaped']:
            self._add_pulse(t, duration)

    def reset_bin_counter(self, t):
        # enqueue: self.seq.reset_bin_counter('default')
        self._add_command(t,
                          self.seq.reset_bin_counter, 'default')

    def finalize(self):
        # note: no need to call super().finalize() because all markers have already been added.
        if not self.n_triggers:
            return
        if not self._integration_time:
            raise Exception(f'Measurement time not set for channel {self.name}')
        num_bins = self.n_triggers * self.n_repetitions
        self.seq.add_acquisition_bins('default', num_bins)

        if self.rf_source_mode == 'continuous':
            self._add_pulse(0, self.t_end)
        if self._pulse_end > 0:
            self._add_pulse_end()

        self._commands.sort(key=lambda cmd:cmd.time)
        for cmd in self._commands:
            # print(cmd.func.__name__, cmd.args, cmd.kwargs)
            cmd.func(*cmd.args, **cmd.kwargs)

    def get_data_scaling(self):
        if isinstance(self._data_scaling, (Number, None)):
            return self._data_scaling
        return np.array(self._data_scaling)

    def _add_scaling(self, scaling, n):
        if self._data_scaling is None:
            self._data_scaling = scaling
        elif isinstance(self._data_scaling, Number):
            if self._data_scaling == scaling: # @@@ rounding errors...
                pass
            else:
               self._data_scaling = [self._data_scaling] * self.n_triggers
               self._data_scaling[-n:-1] = scaling
        else:
           self._data_scaling += [scaling] * n

    def _add_command(self, t, func, *args, **kwargs):
        self._commands.append(_SeqCommand(t, func, args, kwargs))

    def _add_pulse(self, t, duration):
        t_start = t - self.rf_source.trigger_offset_ns
        if t_start < 0:
            raise Exception('RF source has negative start time. Acquisition triggered too early. '
                            f'Acquisition start: {t}, RF source start: {t_start}')
        t_end = t + duration
        if self.rf_source_mode == 'shaped':
            t_end -= self.rf_source.trigger_offset_ns
        if t_start > self._pulse_end:
            self._add_pulse_end()
            amp0 = self._rf_amplitude
            amp1 = amp0 if self._n_out_ch == 2 else None
            self._add_command(t_start,
                              self.seq.set_offset, amp0, amp1, t_offset=t_start)
        self._pulse_end = t_end

    def _add_pulse_end(self):
        if self._pulse_end > 0:
            t = self._pulse_end
            amp1 = 0.0 if self._n_out_ch == 2 else None
            self._add_command(t,
                              self.seq.set_offset, 0.0, amp1, t_offset=t)
