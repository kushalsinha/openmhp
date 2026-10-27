# Setting up on the FloZF PC (Windows)

1. Install a virtual null-modem pair, for example com0com (open source, signed driver), and
   create a pair such as COM20 <-> COM21. FloZF uses one end, this package the other.
2. In the FloZF project, register a **General serial device** (FloZF manual 5.4.1) named `mhp`
   on COM20, 9600 baud, Add to End = <CR>, Require Response = yes, Wait Timeout 2000 ms.
3. Build the `mhp_server` sequence from `flozf_server_sequence.md`, calling your own validated
   sampling, injection and rinse sequences with the variables it reads (probe, dil1, dil2, vial).
   Give the project a "stop sequence" that turns the pumps off (FloZF manual 1.4.7).
4. On the same PC: `pip install openmhp pyserial`. Copy `config.example.json` to `config.json`,
   set `port` to the other end of the pair (COM21) and `sequence_codes` to the codes your
   `mhp_server` sequence uses.
5. `mhp serve pkg:<this folder> --http <port>`, then start `mhp_server` in FloZF and read
   `connected`. First test: `take_sample` to an archive vial with water in the reactor.

Why this route: FloZF (a LabVIEW application) has no command line, network or COM interface;
its sequences can only reach the outside world through device steps. The general serial device
step "prompt for number" sends a text and parses the reply as a number, and FloZF's if and while
conditions branch on it, which is enough for a request-and-acknowledge loop. Global FIA support
can confirm whether a newer FloZF offers something better.
