# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Dependency tracking for trackable objects."""

import warnings

from absl import logging

from tensorflow.python.eager import def_function
from tensorflow.python.eager import function as defun
from tensorflow.python.training.tracking import base
from tensorflow.python.training.tracking import data_structures
from tensorflow.python.util.tf_export import tf_export


@tf_export("__internal__.tracking.AutoTrackable", v1=[])
class AutoTrackable(base.Trackable):
  """Manages dependencies on other objects.

  `Trackable` objects may have dependencies: other `Trackable` objects
  which should be saved if the object declaring the dependency is saved. A
  correctly saveable program has a dependency graph such that if changing a
  global variable affects an object (e.g. changes the behavior of any of its
  methods) then there is a chain of dependencies from the influenced object to
  the variable.

  Dependency edges have names, and are created implicitly when a
  `Trackable` object is assigned to an attribute of another
  `Trackable` object. For example:

  ```
  obj = Trackable()
  obj.v = ResourceVariable(0.)
  ```

  The `Trackable` object `obj` now has a dependency named "v" on a
  variable.

  `Trackable` objects may specify `Tensor`s to be saved and restored
  directly (e.g. a `Variable` indicating how to save itself) rather than through
  dependencies on other objects. See
  `Trackable._gather_saveables_for_checkpoint` for details.
  """

  def __setattr__(self, name, value):
    """Support self.foo = trackable syntax."""
    try:
      if getattr(self, name) is value:
        # Short circuit for `self.$x = self.$x`.
        return
    except AttributeError:
      pass

    if getattr(self, "_self_setattr_tracking", True):
      value = data_structures.sticky_attribute_assignment(
          trackable=self, value=value, name=name)
    super(AutoTrackable, self).__setattr__(name, value)

  def __delattr__(self, name):
    self._delete_tracking(name)
    super(AutoTrackable, self).__delattr__(name)

  def _no_dependency(self, value):
    """Override to allow TrackableBase to disable dependency tracking."""
    return data_structures.NoDependency(value)

  def _list_functions_for_serialization(self, unused_serialization_cache):
    """Return a dict of `Function`s of a trackable."""
    functions = {}
    try:
      # We get the attributes, suppressing warnings and exceptions.
      logging_verbosity = logging.get_verbosity()
      logging.set_verbosity(logging.FATAL)
      for attribute_name in dir(self):
        try:
          with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            attribute_value = getattr(self, attribute_name, None)
        except Exception:  # pylint: disable=broad-except
          # NOTE: If we make the exception catching here less broad, we might
          # need to revisit `finally` block below.
          # We really don't want to throw an exception just because some
          # object's attribute accessor is broken.
          attribute_value = None
        if isinstance(attribute_value, (def_function.Function,
                                        defun.ConcreteFunction)):
          functions[attribute_name] = attribute_value
    finally:
      logging.set_verbosity(logging_verbosity)

    return functions

  def _delete_tracking(self, name):
    """Removes the tracking of name."""
    self._maybe_initialize_trackable()
    if name in self._unconditional_dependency_names:
      del self._unconditional_dependency_names[name]
      for index, (dep_name, _) in enumerate(
          self._unconditional_checkpoint_dependencies):
        if dep_name == name:
          del self._unconditional_checkpoint_dependencies[index]
          break

  def _add_trackable_child(self, name, value):
    self.__setattr__(name, value)
