# Methods on this freeze dryer

A lyophilisation cycle is a recipe held in the controller (LyoS / SCADA on a LyoStar, LPCplus
on an Epsilon): freezing, optional annealing, primary drying at a shelf temperature below the
product's collapse temperature and a controlled chamber pressure, then secondary drying. The
recipe is written and validated in the controller software per product; this package only
selects it by number. A method record here therefore holds the **recipe number** that is
validated for a compound, so `mhp_method op='find'` with the compound answers which recipe to
start and `start_recipe` runs it with provenance (project, method, version, hash) on the job.

`example/mannitol-sucrose-5pct.yaml` is an example record written through the twin's
`methods/save` (so it carries a `validated` block). Its recipe number 3 is a placeholder: make a
project folder for your product, save your own record through `methods/save`, and retire or
delete the example. The runs and history files beside a method are appended by the device.
