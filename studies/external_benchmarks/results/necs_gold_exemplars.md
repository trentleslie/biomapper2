# NECS gold-disagreement exemplar set

> Source values (compound name, InChIKeys, SMILES, formula) are extracted from the supplement of Monti et al. 2026, GeroScience, doi:10.1007/s11357-026-02174-2 (Table S1 / MOESM5), licensed CC BY-NC-ND 4.0. Reproduced with attribution for non-commercial research; the KIND/defect classification and repair verdicts are this work's own analysis.

Disagreements at `block1+block2[:8]`: **182** (offline-resolved 96, pending external anchor 83).

Each row is verifiable from the single published MOESM5 file. `undecidable` rows are listed,
not dropped; no rate is computed across them.

## By kind

| kind | n |
|---|---|
| completeness | 79 |
| stereo_conflict | 44 |
| kind_b_structure | 30 |
| stereo_odd | 9 |
| corrupt | 9 |
| kind_a_bad_key | 8 |
| undecidable | 3 |

## Exemplars

| name | legacy key | modern key | formula | kind | arbiter |
|---|---|---|---|---|---|
| 3-hydroxyisobutyrate | `DBXBTMSZEOQQDU-REWHXWOFAW` | `DBXBTMSZEOQQDU-VKHMYHEASA-N` | C4H8O3 | completeness | modern |
| 3-hydroxy-3-methylglutarate | `NPOAOTPXWNWTSH-NUQVWONBAH` | `NPOAOTPXWNWTSH-UHFFFAOYSA-N` | C6H10O5 | stereo_odd | — |
| homovanillate (hva) | `QRMZSPFSDQBLIX-REWHXWOFAT` | `QRMZSPFSDQBLIX-UHFFFAOYSA-N` | C9H10O4 | stereo_odd | — |
| 4-hydroxyphenylacetate | `XQXPVVBIMDBYFF-REWHXWOFAL` | `XQXPVVBIMDBYFF-UHFFFAOYSA-N` | C8H8O3 | stereo_odd | — |
| n6,n6,n6-trimethyllysine | `MXNRLFUSFKVQSK-UHFFFAOYAO` | `MXNRLFUSFKVQSK-QMMMGPOBSA-N` | C9H20N2O2 | completeness | modern |
| n-formylmethionine | `PYUSHNKNPOHWEZ-YFKPBYRVBS` | `PYUSHNKNPOHWEZ-RXMQYKEDSA-N` | C6H11NO3S | completeness | modern |
| adenosine 5'-monophosphate (amp) | `UDMBCSSLTHHNCD-RWLQFSFNBF` | `UDMBCSSLTHHNCD-KQYNXXCUSA-N` | C10H14N5O7P | completeness | modern |
| arginine | `ODKSFYDXXFIFQN-UHFFFAOYAT` | `ODKSFYDXXFIFQN-BYPYZUCNSA-N` | C6H14N4O2 | completeness | modern |
| cholesterol | `HVYWMOMLDIMFJA-LBHVWCRMBB` | `HVYWMOMLDIMFJA-DPAQBDIFSA-N` | C27H46O | stereo_conflict | — |
| cortisone | `IWIJFUQFXLWZIA-UHFFFAOYAP` | `MFYSYFVPBJMHGN-ZPOLXVRWSA-N` | C21H28O5 | kind_a_bad_key | modern |
| cysteinylglycine | `ZUKPVRWZDMRIEO-UHFFFAOYAS` | `ZUKPVRWZDMRIEO-VKHMYHEASA-N` | C5H10N2O3S | completeness | modern |
| cystine | `LEVWYRKDKASIDU-UHFFFAOYAA` | `LEVWYRKDKASIDU-IMJSIDKUSA-N` | C6H12N2O4S2 | completeness | modern |
| sphingosine | `WWUZIQQURGPMPG-CCEZHUSRBL` | `WWUZIQQURGPMPG-KRWOKUGFSA-N` | C18H37NO2 | stereo_conflict | — |
| cystathionine | `ILRYLPWNYFXEMH-UHFFFAOYAH` | `ILRYLPWNYFXEMH-WHFBIAKZSA-N` | C7H14N2O4S | completeness | modern |
| sphinganine | `OTKJDMGTUTTYMP-UHFFFAOYAS` | `OTKJDMGTUTTYMP-ZWKOTPCHSA-N` | C18H39NO2 | completeness | modern |
| glutarate (c5-dc) | `JFCQEDHGNNZCLN-NUQVWONBAE` | `JFCQEDHGNNZCLN-UHFFFAOYSA-N` | C5H8O4 | stereo_odd | — |
| histidine | `HNDVDQJCIGZPNO-UHFFFAOYAG` | `HNDVDQJCIGZPNO-YFKPBYRVSA-N` | C6H9N3O2 | completeness | modern |
| inosine | `UGQMRVRMYYASKQ-DGPXGRDGBU` | `UGQMRVRMYYASKQ-KQYNXXCUSA-N` | C10H12N4O5 | stereo_conflict | — |
| isoleucine | `AGPKZVBTJJNPAG-UHFFFAOYAW` | `AGPKZVBTJJNPAG-WHFBIAKZSA-N` | C6H13NO2 | completeness | modern |
| citrulline | `RHGKLRLOHDJJDR-UHFFFAOYAQ` | `RHGKLRLOHDJJDR-BYPYZUCNSA-N` | C6H13N3O3 | completeness | modern |
| lactose | `GUBGYTABKSRVRQ-DCSYEGIMBP` | `GUBGYTABKSRVRQ-QKKXKWKRSA-N` | C12H22O11 | stereo_conflict | — |
| malate | `BJEPYKJPYRNKOW-UHFFFAOYAM` | `BJEPYKJPYRNKOW-UWTATZPHSA-N` | C4H6O5 | completeness | modern |
| pelargonate (9:0) | `FBUKVWPVBMHYJY-REWHXWOFAZ` | `FBUKVWPVBMHYJY-UHFFFAOYSA-N` | C9H18O2 | stereo_odd | — |
| phosphate | `NBIIXXVUZAFLBC-DFZHHIFOAA` | `NBIIXXVUZAFLBC-UHFFFAOYSA-N` | PH3O4 | stereo_odd | — |
| phytanate | `RLCKHJSFHOZMDR-REWHXWOFAK` | `RLCKHJSFHOZMDR-GUDVDZBRSA-N` | C20H40O2 | completeness | modern |
| lactate | `JVTAAEKCZFNVCJ-UHFFFAOYAX` | `JVTAAEKCZFNVCJ-REOHCLBHSA-N` | C3H6O3 | completeness | modern |
| salicylate | `4000` | `YGSDEFSMJLZEOE-UHFFFAOYSA-N` | C7H6O3 | corrupt | modern |
| glutamate | `WHUUTDBJXJRKMK-UHFFFAOYAD` | `WHUUTDBJXJRKMK-VKHMYHEASA-N` | C5H9NO4 | stereo_conflict | — |
| glucose | `WQZGKKKJIJFFOK-DVKNGEFBBQ` | `WQZGKKKJIJFFOK-GASJEMHNSA-N` | C6H12O6 | stereo_conflict | — |
| alpha-ketobutyrate | `TYEYBOSBBBHJIV-REWHXWOFAN` | `TYEYBOSBBBHJIV-UHFFFAOYSA-N` | C4H6O3 | stereo_odd | — |
| mannose | `GZCGUPFRVQAUEE-KVTDHHQDBB` | `WQZGKKKJIJFFOK-QTVWNMPRSA-N` | C6H12O6 | kind_a_bad_key | modern |
| pseudouridine | `HZIOZCLEXIYJAD-JWMKEVCDBU` | `PTJWIQPHWPFNBW-GBNDHIKLSA-N` | C9H12N2O6 | kind_a_bad_key | modern |
| pyruvate | `LCTONWCANYUPML-REWHXWOFAD` | `LCTONWCANYUPML-UHFFFAOYSA-N` | C3H4O3 | stereo_odd | — |
| xylose | `PYMYPHUHKUWMLA-WISUUJSJBP` | `SRBFZHDQGSBBOR-IOVATXLUSA-N` | C5H10O5 | kind_b_structure | — |
| maltose | `GUBGYTABKSRVRQ-ASMJPISFBF` | `GUBGYTABKSRVRQ-PICCSMPSSA-N` | C12H22O11 | stereo_conflict | — |
| dihydroorotate | `UFIVEPVSAGBUSI-UHFFFAOYAI` | `UFIVEPVSAGBUSI-UWTATZPHSA-N` | C5H6N2O4 | completeness | modern |
| allantoin | `POJWUDADGALRAB-UHFFFAOYAE` | `POJWUDADGALRAB-SFOWXEAESA-N` | C4H6N4O3 | completeness | modern |
| glycerate | `RBNPOMFGQQGHHO-UHFFFAOYAE` | `RBNPOMFGQQGHHO-UWTATZPHSA-N` | C3H6O4 | completeness | modern |
| 5-kete | `4000` | `MEASLHGILYBXFO-XTDASVJISA-N` | C20H30O3 | corrupt | modern |
| n-acetylvaline | `IHYJTAOFMMMOPX-LURJTMIEBI` | `IHYJTAOFMMMOPX-UHFFFAOYSA-N` | C7H13NO3 | completeness | legacy |
| erucate (22:1n9) | `DPUOLQHDNGRHBS-UHFFFAOYAW` | `DPUOLQHDNGRHBS-KTKRTIGZSA-N` | C22H42O2 | stereo_conflict | — |
| alpha-tocopherol | `GVJHHUAWPYXKBD-IEOSBIPEBS` | `ZAKOWWREFLAJOT-CEFNRUSXSA-N` | C31H52O3 | kind_b_structure | — |
| n-carbamoylaspartate | `HLKXYZVTANABHZ-MRIHDYNCBG` | `HLKXYZVTANABHZ-REOHCLBHSA-N` | C5H8N2O5 | stereo_conflict | — |
| vanillylmandelate (vma) | `CGQCWMIAEPEHNQ-UHFFFAOYAY` | `CGQCWMIAEPEHNQ-QMMMGPOBSA-N` | C9H10O5 | completeness | modern |
| 2-aminobutyrate | `QWCKQJZIFLGMSD-GSVOUGTGBL` | `QWCKQJZIFLGMSD-VKHMYHEASA-N` | C4H9NO2 | stereo_conflict | — |
| n-acetylneuraminate | `KBGAYAKRZNYFFG-BOHATCBPBL` | `SQVRNKJHWKZAKO-PFQGKNLYSA-N` | C11H19NO9 | kind_a_bad_key | modern |
| isocitrate | `ODBLHEXUDAPZAU-UHFFFAOYAX` | `ODBLHEXUDAPZAU-ZAFYKAAXSA-N` | C6H8O7 | stereo_conflict | — |
| 2-hydroxystearate | `KIHBGTRZFAVZRV-UHFFFAOYAD` | `KIHBGTRZFAVZRV-KRWDZBQOSA-N` | C18H36O3 | stereo_conflict | — |
| n1-methyladenosine | `QQBGTSSELNKRID-IOSLPCCCBM` | `GFYLSDSUCHVORB-IOSLPCCCSA-N` | C11H15N5O4 | kind_a_bad_key | modern |
| choline | `CRBHXDCYXIISFC-UHFFFAOYAW` | `OEYIOHPDSNJKLS-UHFFFAOYSA-N` | C5H14NO | kind_b_structure | — |
| beta-hydroxyisovalerate | `4000` | `AXFYFNCPONWUHW-UHFFFAOYSA-N` | C5H10O3 | corrupt | modern |
| ibuprofen | `HEFNNWSXXWATRW-UHFFFAOYAB` | `HEFNNWSXXWATRW-SNVBAGLBSA-N` | C13H18O2 | completeness | modern |
| 1-palmitoyl-2-linoleoyl-gpi (16:0/18:2) | `BSNJSZUDOMPYIR-DMDPBSJXBZ` | `BSNJSZUDOMPYIR-CUKLWHKZSA-N` | C43H79O13P | stereo_conflict | — |
| glycochenodeoxycholate | `GHCZAUBVMUEKKP-UHFFFAOYAS` | `GHCZAUBVMUEKKP-GYPHWSFCSA-N` | C26H43NO5 | stereo_conflict | — |
| methionine sulfoxide | `QEFRNWWLZKMPFJ-YGVKFDHGBW` | `QEFRNWWLZKMPFJ-ZXPFJRLXSA-N` | C5H11NO3S | stereo_conflict | — |
| 4-acetamidophenylglucuronide | `IPROLSVTVHAQLE-UHFFFAOYAX` | `IPROLSVTVHAQLE-BYNIDDHOSA-N` | C14H17NO8 | completeness | modern |
| 5-hydroxylysine | `YSMODUONRAFBET-UHFFFAOYAX` | `YSMODUONRAFBET-UHNVWZDZSA-N` | C6H14N2O3 | stereo_conflict | — |
| glucuronate | `IAJILQKETJEXLJ-QTBDOELSBX` | `AEMOLEFTQBMNLQ-AQKNRBDQSA-N` | C6H10O7 | kind_a_bad_key | modern |
| glycerol 3-phosphate | `AWUCVROLDVIAJX-UHFFFAOYAM` | `AWUCVROLDVIAJX-GSVOUGTGSA-N` | C3H9O6P | completeness | modern |
| imidazole lactate | `ACZFBYCNAVEFLC-YFKPBYRVBI` | `JTYMXXCJQKGGFG-UHFFFAOYSA-N` | C6H8N2O3 | kind_b_structure | — |
| n-acetylglutamate | `RFMMMVDNIPUKGG-QUCRTXIXBK` | `RFMMMVDNIPUKGG-YFKPBYRVSA-N` | C7H11NO5 | stereo_conflict | — |
| tartarate | `FEWJPZIEWOKRBE-UHFFFAOYAZ` | `FEWJPZIEWOKRBE-JCYAYHJZSA-N` | C4H6O6 | stereo_conflict | — |
| 2-isopropylmalate | `BITYXLXUCSKTJS-UHFFFAOYAE` | `BITYXLXUCSKTJS-ZETCQYMHSA-N` | C7H12O5 | completeness | modern |
| glycodeoxycholate | `WVULKSPCQVQLCU-ZGFCPQMKBG` | `WVULKSPCQVQLCU-BUXLTGKBSA-N` | C26H43NO5 | stereo_conflict | — |
| quinate | `AAWZDTNXLSGCEK-WYWMIBKRBU` | `AAWZDTNXLSGCEK-LNVDRNJUSA-N` | C7H12O6 | stereo_conflict | — |
| phenyllactate (pla) | `VOXXWSYKYCBWHO-UHFFFAOYAI` | `VOXXWSYKYCBWHO-QMMMGPOBSA-N` | C9H10O3 | completeness | modern |
| palmitoylcarnitine (c16) | `XOMRRQXKHMYMOC-UHFFFAOYAU` | `XOMRRQXKHMYMOC-OAQYLSRUSA-N` | C23H45NO4 | completeness | modern |
| hexanoylcarnitine (c6) | `VVPRQWTYSNDTEA-UHFFFAOYAN` | `VVPRQWTYSNDTEA-LLVKDONJSA-N` | C13H25NO4 | completeness | modern |
| acetylcarnitine (c2) | `RDHQFKQIGNGIED-MRVPVSSYBU` | `RDHQFKQIGNGIED-QMMMGPOBSA-N` | C9H17NO4 | stereo_conflict | — |
| erythritol | `UNXHWFMMPAWVPI-UHFFFAOYAU` | `UNXHWFMMPAWVPI-ZXZARUISSA-N` | C4H10O4 | completeness | modern |
| 2-linoleoylglycerol (18:2) | `IEPGNWMPIFDNSD-HZJYTTRNBY` | `WECGLUPZRHILCT-HZJYTTRNSA-N` | C21H38O4 | undecidable | — |
| threonate | `JPIJQSOTBSSVTP-GBXIJSLDBD` | `JPIJQSOTBSSVTP-STHAYSLISA-N` | C4H8O5 | completeness | modern |
| galactonate | `RGHNJXZEOKUKBD-SQOUGZDYBY` | `RGHNJXZEOKUKBD-MGCNEYSASA-N` | C6H12O7 | stereo_conflict | — |
| androsterone sulfate | `ZMITXKRGXGRMKS-CZTOYULQBN` | `ZMITXKRGXGRMKS-HLUDHZFRSA-N` | C19H30O5S | stereo_conflict | — |
| gamma-glutamylvaline | `SITLTJHOQZFJGG-UUEFVBAFBQ` | `AQAKHZVPOOGUCK-XPUUQOCRSA-N` | C10H18N2O5 | kind_a_bad_key | modern |
| propionylcarnitine (c3) | `UFAHZIUFPNSHSL-UHFFFAOYAT` | `UFAHZIUFPNSHSL-MRVPVSSYSA-N` | C10H19NO4 | completeness | modern |
| pro-hydroxy-pro | `ONPXCLZMBSJLSP-ALKRTJFJBT` | `ONPXCLZMBSJLSP-CSMHCCOUSA-N` | C10H16N2O4 | stereo_conflict | — |
| docosapentaenoate (n3 dpa; 22:5n3) | `YUFFSWGQGVEMMI-RCHUDCCIBW` | `AVKOENOBFIYBSA-WMPRHZDHSA-N` | C22H34O2 | kind_b_structure | — |
| adrenate (22:4n6) | `TWSWSIQAPQLDBP-CGRWFSSPBH` | `TWSWSIQAPQLDBP-DOFZRALJSA-N` | C22H36O2 | stereo_conflict | — |
| guanidinosuccinate | `VVHOUVWJCQOYGG-UHFFFAOYAC` | `VVHOUVWJCQOYGG-REOHCLBHSA-N` | C5H9N3O4 | completeness | modern |
| i-urobilinogen | `OBHRVMZSZIDDEK-UHFFFAOYAH` | `VKGRRZVYCXLHII-OLFWPHQKSA-N` | C33H48N4O6 | kind_b_structure | — |
| octanoylcarnitine (c8) | `CXTATJFJDMJMIY-UHFFFAOYAP` | `CXTATJFJDMJMIY-CYBMUJFWSA-N` | C15H29NO4 | completeness | modern |
| tauro-beta-muricholate | `XSOLDPYUICCHJX-OEYGYFRSBZ` | `XSOLDPYUICCHJX-UZUDEGBHSA-N` | C26H45NO7S | stereo_conflict | — |
| decanoylcarnitine (c10) | `LZOSYCMHQXPBFU-UHFFFAOYAC` | `LZOSYCMHQXPBFU-OAHLLOKOSA-N` | C17H33NO4 | completeness | modern |
| n-acetylglutamine | `KSMRODHGGIIXDV-YFKPBYRVBV` | `KSMRODHGGIIXDV-UHFFFAOYSA-N` | C7H12N2O4 | completeness | legacy |
| 1-palmitoyl-gpc (16:0) | `ASWBNKHCZGQVJV-UHFFFAOYAM` | `ASWBNKHCZGQVJV-HSZRJFAPSA-N` | C24H50NO7P | completeness | modern |
| myristoylcarnitine (c14) | `PSHXNVGSVNEJBD-UHFFFAOYAV` | `PSHXNVGSVNEJBD-LJQANCHMSA-N` | C21H41NO4 | completeness | modern |
| n-acetylthreonine | `PEDXUVCGOLSNLQ-UHFFFAOYAC` | `PEDXUVCGOLSNLQ-WUJLRWPWSA-N` | C6H11NO4 | completeness | modern |
| n-acetylisoleucine | `JDTWZSUNGHMMJM-MSZQBOFLBT` | `JDTWZSUNGHMMJM-FSPLSTOPSA-N` | C8H15NO3 | undecidable | — |
| hyocholate | `DKPMWHFRUGMUKF-OAEKOJLIBK` | `DKPMWHFRUGMUKF-KWXDGCAGSA-N` | C24H40O5 | stereo_conflict | — |
| epiandrosterone sulfate | `ZMITXKRGXGRMKS-KZBQTZLVBC` | `QGXBDMJGAMFCBF-LUJOEAJASA-N` | C19H30O2 | kind_b_structure | — |
| gamma-glutamyltryptophan | `CATMPQFFVNKDEY-AAEUAGOBBU` | `CATMPQFFVNKDEY-UHFFFAOYSA-N` | C16H19N3O5 | completeness | legacy |
| alpha-hydroxyisovalerate | `NGEWQZIDQIYUNV-UHFFFAOYAS` | `NGEWQZIDQIYUNV-BYPYZUCNSA-N` | C5H10O3 | completeness | modern |
| hydroxybupropion | `RCOBKSKAZMVBHT-NCWAPJAIBS` | `AKOAEVOSDHIVFX-UHFFFAOYSA-N` | C13H18ClNO2 | kind_b_structure | — |
| gamma-glutamylthreonine | `GWNXFCYUJXASDX-JUZNGCLZBW` | `GWNXFCYUJXASDX-ZDLURKLDSA-N` | C9H16N2O6 | undecidable | — |
| p-cresol sulfate | `WGNAKZGUSRVWRH-REWHXWOFAB` | `WGNAKZGUSRVWRH-UHFFFAOYSA-N` | C7H8O4S | stereo_odd | — |
| salicyluric glucuronide* | `OEPADIDIUZTYOX-UHFFFAOYAT` | `OEPADIDIUZTYOX-QKZHPOIUSA-N` | C15H17NO10 | completeness | modern |
| linolenate [alpha or gamma; (18:3n3 or 6)] | `DTOSIQBPPRVQHS-PDBXOOCHBH` | `VZCCETWTMQHEPK-QNEBEIHSSA-N` | C18H30O2 | kind_b_structure | — |
| laurylcarnitine (c12) | `FUJLYHJROOYKRA-UHFFFAOYAK` | `FUJLYHJROOYKRA-QGZVFWFLSA-N` | C19H37NO4 | completeness | modern |
| isovalerylcarnitine (c5) | `IGQBPDJNUXPEMT-UHFFFAOYAB` | `IGQBPDJNUXPEMT-SNVBAGLBSA-N` | C12H23NO4 | completeness | modern |
| n1-methylinosine | `WJNGQIYEQLPJMN-UHFFFAOYAL` | `WJNGQIYEQLPJMN-IOSLPCCCSA-N` | C11H14N4O5 | completeness | modern |
| n6-carbamoylthreonyladenosine | `GYCVHQYQICRFAX-GQFURFNTBM` | `UNUYMBPXEFMLNW-DWVDDHQFSA-N` | C15H20N6O8 | kind_a_bad_key | modern |
| phenylacetylglutamine | `JFLIEFSWGNOPJJ-UHFFFAOYAD` | `JFLIEFSWGNOPJJ-JTQLQIEISA-N` | C13H16N2O4 | stereo_conflict | — |
| cysteine-glutathione disulfide | `BNRXZEPOHPEEAS-UHFFFAOYAL` | `GNTARDAHCXNJEX-ATVXKPNKSA-N` | C13H22N4O8S2 | kind_b_structure | — |
| 1-palmitoyl-gpa (16:0) | `YNDYKPRNFWPPFU-GOSISDBHBW` | `YNDYKPRNFWPPFU-UHFFFAOYSA-N` | C19H39O7P | completeness | legacy |
| gamma-glutamylisoleucine* | `SNCKGJWJABDZHI-SIPWABPFBP` | `SNCKGJWJABDZHI-ZKWXMUAHSA-N` | C11H20N2O5 | stereo_conflict | — |
| 2-hydroxy-3-methylvalerate | `RILPIWOPNGRASR-UHFFFAOYAI` | `RILPIWOPNGRASR-RFZPGFLSSA-N` | C6H12O3 | completeness | modern |
| gulonate* | `RGHNJXZEOKUKBD-NRXMZTRTBF` | `RGHNJXZEOKUKBD-KKQCNMDGSA-N` | C6H12O7 | stereo_conflict | — |
| glutarylcarnitine (c5-dc) | `NXJAXUYOQLTISD-UHFFFAOYAA` | `NXJAXUYOQLTISD-VIFPVBQESA-N` | C12H21NO6 | completeness | modern |
| 2-methylmalonylcarnitine (c4-dc) | `XROYFEWIXXCPAW-UHFFFAOYAB` | `XROYFEWIXXCPAW-MQWKRIRWSA-N` | C11H19NO6 | completeness | modern |
| cholesterol sulfate | `BHYOQNUELFTYRT-WHYDCBPWBW` | `BHYOQNUELFTYRT-DPAQBDIFSA-N` | C27H46O4S | completeness | modern |
| 7-alpha-hydroxy-3-oxo-4-cholestenoate (7-hoca) | `SATGKQGFUDXGAX-MYWFJNCABU` | `CFLVYJJIZHNITM-NLXMLWGDSA-N` | C27H42O4 | kind_b_structure | — |
| 3beta,7alpha-dihydroxy-5-cholestenoate | `GYJSAWZGYQXRBS-GRJZKGIBBR` | `PXHCARRJGFGPAC-YCBRVCGJSA-N` | C27H44O4 | kind_b_structure | — |
| n-acetyl-aspartyl-glutamate (naag) | `OPVPGKGADVGKTG-UHFFFAOYAF` | `OPVPGKGADVGKTG-NKWVEPMBSA-N` | C11H16N2O8 | completeness | modern |
| 1-myristoylglycerol (14:0) | `DCBSHORRWZKAKO-UHFFFAOYAJ` | `DCBSHORRWZKAKO-INIZCTEOSA-N` | C17H34O4 | completeness | modern |
| glycerophosphoethanolamine | `JZNWSCPGTDBMEW-UHFFFAOYAI` | `FRMZOWIQVCBEAC-UHFFFAOYSA-N` | C5H14NO6P | kind_b_structure | — |
| 1-ribosyl-imidazoleacetate* | `AHPWEWASPTZMEK-UHFFFAOYAY` | `AHPWEWASPTZMEK-PEBGCTIMSA-N` | C10H14N2O6 | completeness | modern |
| 1-stearoyl-gpa (18:0) | `LAYXSTYJRSVXIH-UHFFFAOYAP` | `STTKJLVEXMKLNA-CQSZACIVSA-N` | C15H31O7P | kind_b_structure | — |
| dihomo-linolenate (20:3n3 or n6) | `AHANXAKGNAKFSK-PDBXOOCHBM` | `HOBAELRKJCKHQD-QNEBEIHSSA-N` | C20H34O2 | kind_b_structure | — |
| mannitol/sorbitol | `FBPFZTCFMRRESA-UHFFFAOYAI` | `FBPFZTCFMRRESA-JGWLITMVSA-N` | C6H14O6 | completeness | modern |
| 4-vinylphenol sulfate | `IETVQHUKTKKBFF-UHFFFAOYAU` | `FUGYGGDSWSUORM-UHFFFAOYSA-N` | C8H8O | kind_b_structure | — |
| thymol sulfate | `NODSEPOUFZPJEQ-UHFFFAOYAU` | `MGSRCZKZVOBKFT-UHFFFAOYSA-N` | C10H14O | kind_b_structure | — |
| 3-methyladipate | `SYEOWUNSTUDKGM-UHFFFAOYAW` | `SYEOWUNSTUDKGM-YFKPBYRVSA-N` | C7H12O4 | completeness | modern |
| pyrraline | `VTYFITADLSVOAS-UHFFFAOYAA` | `SRPREECLSOIPNK-UHFFFAOYSA-N` | C6H7NO2 | kind_b_structure | — |
| desmethylnaproxen | `XWJUDDGELKXYNO-QMMMGPOBBV` | `XWJUDDGELKXYNO-UHFFFAOYSA-N` | C13H12O3 | completeness | legacy |
| o-cresol sulfate | `CYGSXDXRHXMAOV-UHFFFAOYAI` | `WGNAKZGUSRVWRH-UHFFFAOYSA-N` | C7H8O4S | kind_b_structure | — |
| chiro-inositol | `CDAISMWEOUEBRE-LKPKBOIGBG` | `CDAISMWEOUEBRE-SHFUYGGZSA-N` | C6H12O6 | stereo_conflict | — |
| sphinganine-1-phosphate | `YHEDRJPUIRMZMP-UHFFFAOYAT` | `YHEDRJPUIRMZMP-ZWKOTPCHSA-N` | C18H40NO5P | completeness | modern |
| bilirubin (e,e)* | `BPYKTIZUTYGOLE-BMNRKXREBL` | `BPYKTIZUTYGOLE-IFADSCNNSA-N` | C33H36N4O6 | stereo_conflict | — |
| bilirubin (e,z or z,e)* | `BPYKTIZUTYGOLE-VVCLLGATBN` | `BPYKTIZUTYGOLE-IFADSCNNSA-N` | C33H36N4O6 | stereo_conflict | — |
| n-methylproline | `CWLQUGTUXBXTLF-UHFFFAOYAJ` | `CWLQUGTUXBXTLF-YFKPBYRVSA-N` | C6H11NO2 | completeness | modern |
| 21-hydroxypregnenolone disulfate | `CBOVWLYQUCVTFA-WPWXJNKXBZ` | `MOIQRAOBRXUWGN-WPWXJNKXSA-N` | C21H32O3 | kind_b_structure | — |
| 2-hydroxyglutarate | `HWXBTNAVRSUOJR-UHFFFAOYAI` | `HWXBTNAVRSUOJR-VKHMYHEASA-N` | C5H8O5 | completeness | modern |
| gamma-cehc | `VMJQLPNCUPGMNQ-UHFFFAOYAS` | `WTGHQIKMADLFAH-UHFFFAOYSA-N` | C15H20O3 | kind_b_structure | — |
| 5-methylthioribose** | `OLVVOVIFTBSBBH-UHFFFAOYAD` | `OLVVOVIFTBSBBH-KVTDHHQDSA-N` | C6H12O4S | completeness | modern |
| cysteine sulfinic acid | `ADVPTQAUNPRNPO-UHFFFAOYAU` | `ADVPTQAUNPRNPO-REOHCLBHSA-N` | C3H7NO4S | completeness | modern |
| 5-hete | `KGIJOOYOSFUGPC-XTDASVJIBK` | `KGIJOOYOSFUGPC-JGKLHWIESA-N` | C20H32O3 | stereo_conflict | — |
| ergothioneine | `SSISHJJTAXXQAX-UHFFFAOYAO` | `SSISHJJTAXXQAX-ZETCQYMHSA-N` | C9H15N3O2S | completeness | modern |
| 12-hete | `ZNHVWPKMFKADKW-VXBMJZGYBY` | `ZNHVWPKMFKADKW-LQWMCKPYSA-N` | C20H32O3 | stereo_conflict | — |
| n-acetyl-3-methylhistidine* | `FKTXRTPBUWLETL-UHFFFAOYAZ` | `FKTXRTPBUWLETL-QMMMGPOBSA-N` | C9H13N3O3 | completeness | modern |
| 4-cholesten-3-one | `NYOXRYYXRWJDKP-UHFFFAOYAV` | `NYOXRYYXRWJDKP-GYKMGIIDSA-N` | C27H44O | completeness | modern |
| dexpanthenol | `SNPLKNRPJHDVJA-UHFFFAOYAQ` | `SNPLKNRPJHDVJA-ZETCQYMHSA-N` | C9H19NO4 | completeness | modern |
| ibuprofen acyl glucuronide | `ABOLXXZAJIAUGR-JPMMFUSZBB` | `ABOLXXZAJIAUGR-LEBSGKMFSA-N` | C19H26O8 | stereo_conflict | — |
| omeprazole | `SUBDBMMJDZJVOS-UHFFFAOYAZ` | `SUBDBMMJDZJVOS-XMMPIXPASA-N` | C17H19N3O3S | completeness | modern |
| atenolol | `METKIMKYRPQLGS-UHFFFAOYAT` | `METKIMKYRPQLGS-LBPRGKRZSA-N` | C14H22N2O3 | completeness | modern |
| ethyl glucuronide | `IWJBVMJWSPZNJH-XWBUKDKVBJ` | `IWJBVMJWSPZNJH-UQGZVRACSA-N` | C8H14O7 | stereo_conflict | — |
| glycoursodeoxycholate | `4000` | `GHCZAUBVMUEKKP-XROMFQGDSA-N` | C26H43NO5 | corrupt | modern |
| tauroursodeoxycholate | `4000` | `BHTRKEVKTKCXOH-LBSADWJPSA-N` | C26H45NO6S | corrupt | modern |
| ursocholate | `4000` | `BHQCQFFYRZLCQQ-UTLSPDKDSA-N` | C24H40O5 | corrupt | modern |
| s-methylcysteine sulfoxide | `4000` | `ZZLHPCSGGOGHFW-UHFFFAOYSA-N` | C4H9NO3S | corrupt | modern |
| docosadioate (c22-dc) | `4000` | `SAOKZLXYCUGLFA-UHFFFAOYSA-N` | C22H42O4 | corrupt | modern |
| 16-hydroxypalmitate | `4000` | `UGAGPNKCDRTDHP-UHFFFAOYSA-N` | C16H32O3 | corrupt | modern |
| quinine | `LOUPRKONTZGTKE-WGFDLZGGBH` | `LOUPRKONTZGTKE-WZBLMQSHSA-N` | C20H24N2O2 | stereo_conflict | — |
| isoleucylglycine | `UCGDDTHMMVWVMV-UHFFFAOYAU` | `UCGDDTHMMVWVMV-FSPLSTOPSA-N` | C8H16N2O3 | completeness | modern |
| leucylalanine | `HSQGMTRYSIHDAC-UHFFFAOYAG` | `HSQGMTRYSIHDAC-BQBZGAKWSA-N` | C9H18N2O3 | completeness | modern |
| leucylglycine | `LESXFEZIFXFIQR-UHFFFAOYAD` | `LESXFEZIFXFIQR-LURJTMIESA-N` | C8H16N2O3 | completeness | modern |
| 2-o-methylascorbic acid | `RMHBODZVODTFAH-UHFFFAOYAP` | `JBXPKMHATRSERD-WVZVXSGGSA-N` | C7H10O6 | kind_b_structure | — |
| cis-urocanate | `LOIYMIARKYCTBW-UPHRSURJBB` | `LOIYMIARKYCTBW-OWOJBTEDSA-N` | C6H6N2O2 | stereo_conflict | — |
| histidylalanine | `FRJIAZKQGSCKPQ-UHFFFAOYAE` | `FRJIAZKQGSCKPQ-FSPLSTOPSA-N` | C9H14N4O3 | completeness | modern |
| phenylalanylglycine | `GLUBLISJVJFHQS-UHFFFAOYAD` | `GLUBLISJVJFHQS-VIFPVBQESA-N` | C11H14N2O3 | completeness | modern |
| (15:0)-anacardic acid | `ADFWQBGTDJIESE-UHFFFAOYAF` | `KAOMOVYHGLSFHQ-UTOQUPLUSA-N` | C22H32O3 | kind_b_structure | — |
| n-delta-acetylornithine | `SRXKAYJJGAAOBP-UHFFFAOYAF` | `SRXKAYJJGAAOBP-LURJTMIESA-N` | C7H14N2O3 | completeness | modern |
| methionine sulfone | `UCUNFLYVYCGDHP-UHFFFAOYAG` | `UCUNFLYVYCGDHP-BYPYZUCNSA-N` | C5H11NO4S | completeness | modern |
| fructosyllysine | `BFSYFTQDGRDJNV-QCNRFFRDBO` | `BFSYFTQDGRDJNV-AYHFEMFVSA-N` | C12H24N2O7 | stereo_conflict | — |
| octadecanedioylcarnitine (c18-dc)* | `ULCCGBCYWCYNIC-UHFFFAOYAW` | `ULCCGBCYWCYNIC-JOCHJYFZSA-N` | C25H47NO6 | completeness | modern |
| valsartan | `ACWBQPMHZXGDFX-UHFFFAOYAP` | `ACWBQPMHZXGDFX-QFIPXVFZSA-N` | C24H29N5O3 | completeness | modern |
| o-desmethyltramadol glucuronide | `DSBGQRZOJXSECT-VFUSOVNCBT` | `DSBGQRZOJXSECT-VZFNFROLSA-N` | C21H31NO8 | stereo_conflict | — |
| azithromycin | `MQTOSJVFKKJCRP-UHFFFAOYAK` | `MQTOSJVFKKJCRP-BICOPXKESA-N` | C38H72N2O12 | completeness | modern |
| 1-palmitoyl-2-arachidonoyl-gpi (16:0/20:4)* | `KIQYUSYSJTUGFZ-GWAZTMTOBN` | `KIQYUSYSJTUGFZ-LSLODQAYSA-N` | C45H79O13P | stereo_conflict | — |
| ascorbic acid 2-sulfate | `SKKZOYBAANIUOV-ZAFYKAAXBH` | `XDBMXUKHMOFBPJ-ZAFYKAAXSA-N` | C6H8O9S | kind_b_structure | — |
| lisinopril | `RLAWWYSOJDYHDC-UHFFFAOYAB` | `RLAWWYSOJDYHDC-BZSNNMDCSA-N` | C21H31N3O5 | completeness | modern |
| cerotoylcarnitine (c26)* | `KOCKWDDTAHPJSX-UHFFFAOYAQ` | `KOCKWDDTAHPJSX-WJOKGBTCSA-N` | C33H65NO4 | completeness | modern |
| ethyl alpha-glucopyranoside | `WYUFTYLVLQZQNH-UHFFFAOYAZ` | `WYUFTYLVLQZQNH-JAJWTYFOSA-N` | C8H16O6 | completeness | modern |
| n-stearoylserine* | `CLHUCXCVFSEJRR-UHFFFAOYAZ` | `CLHUCXCVFSEJRR-IBGZPJMESA-N` | C21H41NO4 | completeness | modern |
| 3-hydroxystachydrine* | `DJMIFDZBCUUQJN-NTSWFWBYBE` | `DJMIFDZBCUUQJN-GDVGLLTNSA-N` | C7H13NO3 | stereo_conflict | — |
| hydroxyasparagine** | `ZBYVTTSIVDYQSO-REOHCLBHBO` | `KGWIPRBCZYRDNO-REOHCLBHSA-N` | C4H8N2O4 | kind_b_structure | — |
| diacetylspermidine* | `SKQLBVJMDVTJMX-UHFFFAOYAM` | `NPDTUDWGJMBVEP-UHFFFAOYSA-N` | C14H30N4O2 | kind_b_structure | — |
| 10-hydroxywarfarin | `BPZSPAZBZFZZBN-UHFFFAOYAH` | `KLDFTXZRAPVGLB-LDCVWXEPSA-N` | C19H16O5 | kind_b_structure | — |
| 7-hydroxywarfarin | `SKFYEJMLNMTTJA-UHFFFAOYAU` | `BQSUFDMOXLLKQK-OAHLLOKOSA-N` | C19H16O5 | kind_b_structure | — |
| 6-hydroxywarfarin | `IQWPEJBUOJQPDE-UHFFFAOYAN` | `JFCOGWFGPAUYNK-CQSZACIVSA-N` | C19H16O5 | kind_b_structure | — |
| taurochenodeoxycholic acid 3-sulfate | `IJHJZQKOSUFQCX-WZJRQFJBBW` | `YLMCJTQMMGJPIR-BJLOMENOSA-N` | C26H45NO8S2 | kind_b_structure | — |
| (s)-a-amino-omega-caprolactam | `BOWUOGIPSRVRSJ-RXMQYKEDBD` | `BOWUOGIPSRVRSJ-YFKPBYRVSA-N` | C6H12N2O | stereo_conflict | — |
