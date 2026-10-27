# UNICORN OPC Data Access items used here (UNICORN 7.6 OPC Manual, ch. 4)

| Purpose | Item | Values |
|---|---|---|
| Take control | `STATE\AssignState` | write 1 = Control, 0 = View |
| Run state | `STATE\RunState` | Ready, Method Run, System Pause, Hold, Pause Hold, Hold Pause, Manual Pause, Wash, Alarms and errors, Initializing system, Resetting, Starting method run, Starting manual run |
| Who is in control | `STATE\UserInControl` | user name |
| Run commands | `STATE\Command` | write 0 Pause, 1 Hold, 2 Continue, 3 End, 4 Next breakpoint |
| Start a method | `<method_root>\<folder>\<method>\Run Method` | write 0 or 1 = Execute (write variables first) |
| Result name | `<method>\Result Name` | string; the run does not start without one |
| Batch id | `<method>\Batch ID` | string |
| Method variables | `<method>\Method Variable(s)\<name>` | float/int/string/choice; UNICORN rejects out-of-range writes. Not available: scouting, breakpoints, Frac-950 fractionation parameters |
| Start questions | `<method>\Question(s)\<question>` | answers; a mandatory unanswered question blocks the start |
| Live values | `Event\Analog Picture\<sensor>`, `Event\Rundata\<value>` | per instrument configuration |
| Current method, result, block | `Event\Curves\CurrentMethod`, `CurrentResult`, `CurrentBlock` | text |

Cytiva's notes the driver follows: write the parameters before the item that executes them, one
write at a time; do not start manual runs over OPC (start methods); control is only granted if
no UNICORN user holds the system.
