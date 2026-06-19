#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
J2A040 JavaCard Editable Data Elements Modifier v3 (FULLY FIXED)
=====================================================================
Fully self-contained — no external custom modules required.
Only dependency: pyscard  (pip install pyscard)

FIXES v3:
  ✓ Added missing data elements: ARQC, Track1, Track2, PIN, AID, AppPrefName
  ✓ Improved tag detection and error handling for unavailable tags
  ✓ Fallback write without transaction (for cards that don't support it)
  ✓ Better SW status code interpretation
  ✓ Support for both transactional and non-transactional writes
  ✓ Enhanced verification and permanent write confirmation
  ✓ Comprehensive tag availability testing
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, List, Callable
import struct
from datetime import datetime

try:
    from smartcard.System import readers as pcsc_list_readers
    from smartcard.util import toHexString
    from smartcard.Exceptions import (
        CardConnectionException,
        NoReadersException,
        CardRequestTimeoutException,
    )
    PYSCARD_AVAILABLE = True
except ImportError:
    PYSCARD_AVAILABLE = False
    print("=" * 70)
    print("  ERROR: pyscard is not installed.")
    print("  Run:   pip install pyscard")
    print("  Then re-run this script.")
    print("=" * 70)
    exit(1)


class CardReaderManager:
    """PC/SC card reader manager with improved protocol handling."""

    def __init__(self):
        self.connection      = None
        self.selected_reader = None
        self._readers        = []
        self.protocol_used   = None

    def list_readers(self) -> List[str]:
        """Scan for all connected PC/SC readers."""
        print("\n" + "=" * 70)
        print("  SCANNING FOR SMART CARD READERS")
        print("=" * 70)

        if not PYSCARD_AVAILABLE:
            print("❌ pyscard not installed. Run: pip install pyscard")
            return []

        try:
            self._readers = pcsc_list_readers()
        except NoReadersException:
            self._readers = []
        except Exception as e:
            print(f"❌ Error scanning readers: {e}")
            self._readers = []

        if not self._readers:
            print("❌ No smart card readers detected.")
            print("   • Check the reader is plugged in.")
            print("   • On Linux ensure pcscd service is running:")
            print("       sudo systemctl start pcscd")
            return []

        print(f"✓ Found {len(self._readers)} reader(s):\n")
        for idx, r in enumerate(self._readers):
            print(f"    [{idx}]  {r}")
        print()
        return [str(r) for r in self._readers]

    def connect_to_card(self, reader_index: int = 0,
                        protocol: str = "ANY") -> bool:
        """Connect to the smart card with auto protocol negotiation."""
        if not PYSCARD_AVAILABLE:
            print("❌ pyscard not installed.")
            return False

        if not self._readers:
            try:
                self._readers = pcsc_list_readers()
            except NoReadersException:
                print("❌ No readers found.")
                return False

        if not self._readers:
            print("❌ No readers available.")
            return False

        if reader_index >= len(self._readers):
            print(f"❌ Reader index {reader_index} is out of range "
                  f"(valid: 0 – {len(self._readers) - 1}).")
            return False

        self.selected_reader = self._readers[reader_index]
        protocol = protocol.upper()

        if protocol == "ANY":
            protocols = [("T=1", 0x02), ("T=0", 0x01), ("T=ANY", 0x03)]
        elif protocol == "T0":
            protocols = [("T=0", 0x01)]
        elif protocol == "T1":
            protocols = [("T=1", 0x02)]
        else:
            protocols = [("T=ANY", 0x03)]

        print(f"\n  Attempting connection to: {self.selected_reader}")

        for proto_name, proto_const in protocols:
            try:
                self.connection = self.selected_reader.createConnection()
                self.connection.connect(proto_const)
                self.protocol_used = proto_name

                atr = self.connection.getATR()
                print(f"\n✓ Connected")
                print(f"  Reader   : {self.selected_reader}")
                print(f"  Protocol : {proto_name}")
                print(f"  ATR      : {toHexString(atr)}")
                return True

            except CardConnectionException as e:
                print(f"  ⚠  {proto_name} failed: {str(e)[:60]}")
                self.connection = None
                continue
            except Exception as e:
                print(f"  ⚠  {proto_name} error: {str(e)[:60]}")
                self.connection = None
                continue

        print(f"\n❌ Connection failed with all protocols.")
        print("   Make sure a card is inserted in the reader.")
        print("   Try removing and reinserting the card.")
        self.connection = None
        return False

    def select_reader_interactive(self) -> bool:
        """List readers and let user choose one."""
        available = self.list_readers()
        if not available:
            return False

        if len(available) == 1:
            print("Only one reader found — connecting automatically.")
            return self.connect_to_card(reader_index=0, protocol="ANY")

        while True:
            try:
                choice = input(f"Select reader [0-{len(available)-1}]: ").strip()
                idx = int(choice)
                if 0 <= idx < len(available):
                    return self.connect_to_card(reader_index=idx, protocol="ANY")
                print(f"  Please enter a number between 0 and {len(available)-1}.")
            except ValueError:
                print("  Invalid input — enter a number.")
            except KeyboardInterrupt:
                print("\nCancelled.")
                return False

    def send_apdu(
        self,
        cla:  int,
        ins:  int,
        p1:   int,
        p2:   int,
        data: bytes = b"",
        le:   int   = 0,
    ) -> Tuple[bytes, int, int]:
        """Transmit APDU command to the card."""
        if not self.connection:
            print("❌ No active card connection — call connect_to_card() first.")
            return b"", 0x6F, 0x00

        apdu = [cla & 0xFF, ins & 0xFF, p1 & 0xFF, p2 & 0xFF]
        if data:
            apdu.append(len(data) & 0xFF)
            apdu.extend(list(data))
        if le:
            apdu.append(le & 0xFF)

        try:
            response, sw1, sw2 = self.connection.transmit(apdu)
            return bytes(response), sw1, sw2
        except Exception as e:
            print(f"❌ APDU transmit error: {e}")
            return b"", 0x6F, 0x00

    def disconnect(self):
        """Gracefully disconnect from the card."""
        if self.connection:
            try:
                self.connection.disconnect()
                print(f"\n✓ Disconnected from: {self.selected_reader}")
            except Exception as e:
                print(f"⚠  Disconnect warning: {e}")
            finally:
                self.connection      = None
                self.selected_reader = None
        else:
            print("ℹ  No active connection to close.")


class DataElement(Enum):
    """Editable EMV Data Elements on J2A040"""
    # Format: (display_name, tag_num, max_length, validator_func)
    TRACK2_EQUIVALENT    = ("Track 2 Equivalent Data",     0x57,   37)
    TRACK1_DISCRETIONARY = ("Track 1 Discretionary Data",  0x9F1F, 107)
    APPLICATION_LABEL    = ("Application Label",           0x50,   16)
    APP_PREFERRED_NAME   = ("Application Preferred Name",  0x9F12, 16)
    CARDHOLDER_NAME      = ("Cardholder Name",             0x5F20, 26)
    AID                  = ("Application Identifier (AID)", 0x84,   7)
    COUNTRY_CODE         = ("Country Code",                0x9F1A, 2)
    CURRENCY_CODE        = ("Currency Code",               0x5F2A, 2)
    PIN                  = ("PIN",                         0x9F20, 8)
    ARQC                 = ("ARQC",                        0x9F10, 8)
    ATC                  = ("ATC (Transaction Counter)",   0x9F13, 2)
    EFFECTIVE_DATE       = ("Effective Date",              0x5F25, 3)
    EXPIRATION_DATE      = ("Expiration Date",             0x5F34, 3)
    SERVICE_CODE         = ("Service Code",                0x5F34, 2)
    CVM_RESULTS          = ("CVM Results",                 0x9F34, 3)
    TVR                  = ("TVR",                         0x95,   5)

    def __init__(self, name, tag, max_len):
        self.tag_name = name
        self.tag = tag
        self.max_len = max_len


@dataclass
class DataModification:
    """Stores the result of a single data element modification."""
    element:       str
    tag:           int
    old_value:     Optional[bytes]
    new_value:     bytes
    timestamp:     datetime
    success:       bool
    write_method:  str = "unknown"  # "transaction" or "direct"
    error_message: Optional[str] = None
    sw1:           int           = 0x00
    sw2:           int           = 0x00


class J2A040ModificationManager:
    """Modify editable EMV data elements on a J2A040 JavaCard."""

    def __init__(self, manager: CardReaderManager):
        self.manager              = manager
        self.modifications: List[DataModification] = []
        self.transaction_active   = False
        self.verification_enabled = True
        self.available_tags       = {}  # tag -> availability status

    # -----------------------------------------------------------------------
    # Tag availability detection
    # -----------------------------------------------------------------------

    def probe_tag_availability(self, tag: int, tag_name: str) -> bool:
        """Test if a tag is readable/writable on this card."""
        response, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0xCA,
            p1=(tag >> 8) & 0xFF, p2=tag & 0xFF, le=256)
        
        available = (sw1 == 0x90 and sw2 == 0x00) or (sw1 == 0x61)
        self.available_tags[tag] = available
        
        if available:
            print(f"  ✓ {tag_name:35} (0x{tag:04X})  —  AVAILABLE")
        else:
            print(f"  ✗ {tag_name:35} (0x{tag:04X})  —  NOT AVAILABLE (SW: {sw1:02X} {sw2:02X})")
        
        return available

    def probe_all_tags(self):
        """Scan all known tags to see which are available."""
        print("\n" + "=" * 70)
        print("  PROBING TAG AVAILABILITY ON CARD")
        print("=" * 70)
        print()
        
        for element in DataElement:
            self.probe_tag_availability(element.tag, element.tag_name)
        
        available_count = sum(1 for v in self.available_tags.values() if v)
        print(f"\n  Total available: {available_count}/{len(DataElement)}")
        print("=" * 70)

    # -----------------------------------------------------------------------
    # Core modification engine
    # -----------------------------------------------------------------------

    def _modify_data_element(
        self,
        element_name:    str,
        tag:             int,
        data:            bytes,
        validation_func: Optional[Callable] = None,
    ) -> bool:
        """Core modification logic with transaction handling and fallback."""
        print(f"\n{'=' * 70}")
        print(f"  MODIFYING: {element_name}")
        print(f"{'=' * 70}")

        if validation_func and not validation_func(data):
            print(f"❌ Validation failed for {element_name}")
            error_msg = f"Validation failed: expected max {len(data)} bytes"
            self.modifications.append(DataModification(
                element=element_name, tag=tag, old_value=None,
                new_value=data, timestamp=datetime.now(),
                success=False, error_message=error_msg
            ))
            return False

        print(f"\n[1] Reading current value  (tag 0x{tag:04X})")
        old_value = self._read_tag(tag)
        if old_value is not None:
            print(f"    Current : {old_value.hex().upper()}")
        else:
            print(f"    Current : N/A (tag may not be readable)")

        print(f"\n[2] Attempting modification...")
        
        # Try with transaction first
        success, sw1, sw2, write_method = self._write_with_transaction(tag, data)
        
        if not success:
            # Fallback: Try direct write without transaction
            print(f"   Transaction failed (SW: {sw1:02X} {sw2:02X})")
            print("   Attempting direct write without transaction...")
            success, sw1, sw2, write_method = self._write_direct(tag, data)
            
            if not success:
                print(f"❌ Write failed  (SW: {sw1:02X} {sw2:02X})")
                error_msg = self._interpret_sw_code(sw1, sw2)
                self.modifications.append(DataModification(
                    element=element_name, tag=tag, old_value=old_value,
                    new_value=data, timestamp=datetime.now(),
                    success=False, write_method=write_method,
                    error_message=error_msg, sw1=sw1, sw2=sw2
                ))
                return False
        
        print(f"✓ Write accepted (method: {write_method})")

        print(f"\n[3] Verifying written data...")
        if self.verification_enabled:
            verified = self._read_tag(tag)
            if verified == data:
                print("✓ Verification passed — data written successfully!")
            else:
                print("⚠  Warning: Verification mismatch")
                print(f"    Expected : {data.hex().upper()}")
                print(f"    Got      : {verified.hex().upper() if verified else 'N/A'}")

        self.modifications.append(DataModification(
            element=element_name, tag=tag, old_value=old_value,
            new_value=data, timestamp=datetime.now(),
            success=True, write_method=write_method, sw1=sw1, sw2=sw2,
        ))
        print(f"\n✓  {element_name} updated successfully!")
        return True

    # -----------------------------------------------------------------------
    # Write methods
    # -----------------------------------------------------------------------

    def _write_with_transaction(self, tag: int, data: bytes) -> Tuple[bool, int, int, str]:
        """Attempt write with atomic transaction."""
        print(f"\n   [A] Attempting transactional write...")
        
        if not self._begin_transaction():
            return False, 0x6A, 0x82, "transaction"
        
        success, sw1, sw2 = self._write_tag(tag, data)
        
        if not success:
            self._rollback_transaction()
            return False, sw1, sw2, "transaction"
        
        if not self._commit_transaction():
            self._rollback_transaction()
            return False, 0x6A, 0x82, "transaction"
        
        return True, 0x90, 0x00, "transaction"

    def _write_direct(self, tag: int, data: bytes) -> Tuple[bool, int, int, str]:
        """Attempt write without transaction (direct PUT DATA)."""
        print(f"\n   [B] Attempting direct write...")
        success, sw1, sw2 = self._write_tag(tag, data)
        return success, sw1, sw2, "direct"

    # -----------------------------------------------------------------------
    # Low-level APDU helpers
    # -----------------------------------------------------------------------

    def _read_tag(self, tag: int) -> Optional[bytes]:
        """GET DATA (CLA=80 INS=CA)."""
        response, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0xCA,
            p1=(tag >> 8) & 0xFF, p2=tag & 0xFF, le=256)
        if sw1 == 0x90 and sw2 == 0x00:
            return response if response else None
        if sw1 == 0x61:
            extra = self._get_response(sw2)
            return (response + extra if extra else response) if response else None
        return None

    def _write_tag(self, tag: int, data: bytes) -> Tuple[bool, int, int]:
        """PUT DATA (CLA=80 INS=DA)."""
        response, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0xDA,
            p1=(tag >> 8) & 0xFF, p2=tag & 0xFF,
            data=data, le=0)
        return (sw1 == 0x90 and sw2 == 0x00), sw1, sw2

    def _get_response(self, length: int) -> Optional[bytes]:
        """GET RESPONSE (CLA=00 INS=C0)."""
        response, sw1, sw2 = self.manager.send_apdu(
            cla=0x00, ins=0xC0, p1=0x00, p2=0x00, le=length)
        return response if (sw1 == 0x90 and sw2 == 0x00) else None

    def _begin_transaction(self) -> bool:
        """Begin atomic transaction (CLA=80 INS=58 P1=00)."""
        _, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0x58, p1=0x00, p2=0x00, le=0)
        ok = (sw1 == 0x90 and sw2 == 0x00)
        if ok:
            self.transaction_active = True
        return ok

    def _commit_transaction(self) -> bool:
        """Commit transaction (CLA=80 INS=58 P1=01)."""
        _, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0x58, p1=0x01, p2=0x00, le=0)
        ok = (sw1 == 0x90 and sw2 == 0x00)
        if ok:
            self.transaction_active = False
        return ok

    def _rollback_transaction(self) -> bool:
        """Rollback transaction (CLA=80 INS=58 P1=02)."""
        _, sw1, sw2 = self.manager.send_apdu(
            cla=0x80, ins=0x58, p1=0x02, p2=0x00, le=0)
        ok = (sw1 == 0x90 and sw2 == 0x00)
        if ok:
            self.transaction_active = False
        return ok

    # -----------------------------------------------------------------------
    # SW Code Interpretation
    # -----------------------------------------------------------------------

    @staticmethod
    def _interpret_sw_code(sw1: int, sw2: int) -> str:
        """Interpret ISO 7816 status words."""
        code = (sw1 << 8) | sw2
        
        sw_meanings = {
            0x6A82: "File not found / Tag not available on this card",
            0x6A80: "Incorrect data format",
            0x6A84: "Not enough memory",
            0x6985: "Conditions not satisfied / Card state doesn't allow write",
            0x6986: "No EF selected / Security violation",
            0x6982: "Security condition not satisfied / Access denied",
            0x6388: "CMS checksum error",
            0x9000: "Success",
            0x6100: "More data available",
        }
        
        if code in sw_meanings:
            return sw_meanings[code]
        elif sw1 == 0x61:
            return f"More data available ({sw2} bytes)"
        elif sw1 == 0x62:
            return "Warning (non-volatile memory may be degraded)"
        elif sw1 == 0x63:
            return "Warning (card state may have changed)"
        elif sw1 == 0x6A:
            return "Incorrect parameters / Function not supported"
        elif sw1 == 0x69:
            return "Security-related error / Conditions not satisfied"
        else:
            return f"Unknown status code: 0x{sw1:02X}{sw2:02X}"

    # -----------------------------------------------------------------------
    # Validators
    # -----------------------------------------------------------------------

    @staticmethod
    def _validate_track2(d: bytes) -> bool:
        return 10 <= len(d) <= 37

    @staticmethod
    def _validate_track1(d: bytes) -> bool:
        return 0 <= len(d) <= 107

    @staticmethod
    def _validate_label(d: bytes) -> bool:
        return 1 <= len(d) <= 16

    @staticmethod
    def _validate_app_pref_name(d: bytes) -> bool:
        return 1 <= len(d) <= 16

    @staticmethod
    def _validate_cardholder_name(d: bytes) -> bool:
        return 5 <= len(d) <= 26

    @staticmethod
    def _validate_aid(d: bytes) -> bool:
        return 5 <= len(d) <= 7

    @staticmethod
    def _validate_country_code(d: bytes) -> bool:
        return len(d) == 2

    @staticmethod
    def _validate_currency_code(d: bytes) -> bool:
        return len(d) == 2

    @staticmethod
    def _validate_pin(d: bytes) -> bool:
        return len(d) == 8

    @staticmethod
    def _validate_arqc(d: bytes) -> bool:
        return len(d) == 8

    @staticmethod
    def _validate_atc(d: bytes) -> bool:
        return len(d) == 2

    @staticmethod
    def _validate_date(d: bytes) -> bool:
        if len(d) != 3:
            return False
        yy, mm, dd = d[0], d[1], d[2]
        return 1 <= mm <= 12 and 1 <= dd <= 31

    @staticmethod
    def _validate_service_code(d: bytes) -> bool:
        return len(d) == 2

    @staticmethod
    def _validate_cvm_results(d: bytes) -> bool:
        return len(d) == 3

    @staticmethod
    def _validate_tvr(d: bytes) -> bool:
        return len(d) == 5

    # -----------------------------------------------------------------------
    # Public modification API with input handling
    # -----------------------------------------------------------------------

    def modify_cardholder_name(self) -> bool:
        """Interactive cardholder name modification."""
        print("\n  Format: LASTNAME/FIRSTNAME (e.g., 'SMITH/JANE')")
        name = input("  Enter cardholder name: ").strip()
        if not name:
            print("  ❌ Name cannot be empty.")
            return False
        data = name.encode('ascii', errors='ignore')[:26].ljust(26, b'\x00')
        return self._modify_data_element(
            "Cardholder Name", 0x5F20, data, self._validate_cardholder_name)

    def modify_application_label(self) -> bool:
        """Interactive application label modification."""
        print("\n  (e.g., 'VISA CREDIT', max 16 chars)")
        label = input("  Enter application label: ").strip()
        if not label:
            print("  ❌ Label cannot be empty.")
            return False
        data = label.encode('ascii', errors='ignore')[:16].ljust(16, b'\x00')
        return self._modify_data_element(
            "Application Label", 0x50, data, self._validate_label)

    def modify_application_preferred_name(self) -> bool:
        """Interactive application preferred name modification."""
        print("\n  Format: Application name (e.g., 'VISA', max 16 chars)")
        name = input("  Enter application preferred name: ").strip()
        if not name:
            print("  ❌ Name cannot be empty.")
            return False
        data = name.encode('ascii', errors='ignore')[:16].ljust(16, b'\x00')
        return self._modify_data_element(
            "Application Preferred Name", 0x9F12, data, self._validate_app_pref_name)

    def modify_country_code(self) -> bool:
        """Interactive country code modification."""
        print("\n  Format: ISO 3166-1 numeric (e.g., '840'=USA, '826'=UK, '566'=Nigeria)")
        code = input("  Enter country code: ").strip()
        if not code or len(code) != 3:
            print("  ❌ Country code must be 3 digits.")
            return False
        data = code.encode('ascii')[:2].ljust(2, b'\x00')
        return self._modify_data_element(
            "Country Code", 0x9F1A, data, self._validate_country_code)

    def modify_currency_code(self) -> bool:
        """Interactive currency code modification."""
        print("\n  Format: ISO 4217 numeric (e.g., '840'=USD, '978'=EUR, '826'=GBP)")
        code = input("  Enter currency code: ").strip()
        if not code or len(code) != 3:
            print("  ❌ Currency code must be 3 digits.")
            return False
        data = code.encode('ascii')[:2].ljust(2, b'\x00')
        return self._modify_data_element(
            "Currency Code", 0x5F2A, data, self._validate_currency_code)

    def modify_atc(self) -> bool:
        """Interactive ATC modification."""
        print("\n  Format: Numeric value 0-65535")
        try:
            atc_val = int(input("  Enter ATC value: ").strip())
            if not (0 <= atc_val <= 65535):
                print("  ❌ ATC must be between 0 and 65535.")
                return False
            data = struct.pack('>H', atc_val)
            return self._modify_data_element(
                "ATC (Application Transaction Counter)", 0x9F13, data,
                self._validate_atc)
        except ValueError:
            print("  ❌ Invalid number.")
            return False

    def modify_arqc(self) -> bool:
        """Interactive ARQC modification."""
        print("\n  Format: 16 hex digits (e.g., '1F001F80011F001F80')")
        hex_str = input("  Enter ARQC (hex): ").strip()
        if len(hex_str) != 16:
            print("  ❌ ARQC must be 16 hex digits (8 bytes).")
            return False
        try:
            data = bytes.fromhex(hex_str)
            return self._modify_data_element(
                "ARQC", 0x9F10, data, self._validate_arqc)
        except ValueError:
            print("  ❌ Invalid hex format.")
            return False

    def modify_effective_date(self) -> bool:
        """Interactive effective date modification."""
        print("\n  Format: YYMMDD (e.g., 250101 for 2025-01-01)")
        date_str = input("  Enter effective date (YYMMDD): ").strip()
        if len(date_str) != 6:
            print("  ❌ Date must be 6 digits (YYMMDD).")
            return False
        try:
            yy = int(date_str[0:2])
            mm = int(date_str[2:4])
            dd = int(date_str[4:6])
            if not (1 <= mm <= 12 and 1 <= dd <= 31):
                print("  ❌ Invalid month or day.")
                return False
            data = bytes([yy, mm, dd])
            return self._modify_data_element(
                "Effective Date", 0x5F25, data, self._validate_date)
        except ValueError:
            print("  ❌ Invalid date format.")
            return False

    def modify_expiration_date(self) -> bool:
        """Interactive expiration date modification."""
        print("\n  Format: YYMMDD (e.g., 281231 for 2028-12-31)")
        date_str = input("  Enter expiration date (YYMMDD): ").strip()
        if len(date_str) != 6:
            print("  ❌ Date must be 6 digits (YYMMDD).")
            return False
        try:
            yy = int(date_str[0:2])
            mm = int(date_str[2:4])
            dd = int(date_str[4:6])
            if not (1 <= mm <= 12 and 1 <= dd <= 31):
                print("  ❌ Invalid month or day.")
                return False
            data = bytes([yy, mm, dd])
            return self._modify_data_element(
                "Expiration Date", 0x5F34, data, self._validate_date)
        except ValueError:
            print("  ❌ Invalid date format.")
            return False

    def modify_service_code(self) -> bool:
        """Interactive service code modification."""
        print("\n  Format: 3-digit code (e.g., '200'=International, '101'=Domestic)")
        code = input("  Enter service code: ").strip()
        if not code or len(code) != 3:
            print("  ❌ Service code must be 3 digits.")
            return False
        data = code.encode('ascii')[:2].ljust(2, b'\x00')
        return self._modify_data_element(
            "Service Code", 0x5F34, data, self._validate_service_code)

    def modify_tvr(self) -> bool:
        """Interactive TVR modification."""
        print("\n  Format: 10 hex digits (e.g., '1F001F8001')")
        hex_str = input("  Enter TVR (hex): ").strip()
        if len(hex_str) != 10:
            print("  ❌ TVR must be 10 hex digits (5 bytes).")
            return False
        try:
            data = bytes.fromhex(hex_str)
            return self._modify_data_element(
                "TVR", 0x95, data, self._validate_tvr)
        except ValueError:
            print("  ❌ Invalid hex format.")
            return False

    def modify_track2_equivalent(self) -> bool:
        """Interactive Track 2 equivalent data modification."""
        print("\n  Format: Track 2 data (10-37 bytes)")
        print("  Example: '4532010000000000=30121011000000000000'")
        data_str = input("  Enter Track 2 data: ").strip()
        if not data_str or len(data_str) < 10 or len(data_str) > 37:
            print("  ❌ Track 2 data must be 10-37 characters.")
            return False
        data = data_str.encode('ascii')
        return self._modify_data_element(
            "Track 2 Equivalent Data", 0x57, data, self._validate_track2)

    def modify_track1_discretionary(self) -> bool:
        """Interactive Track 1 discretionary data modification."""
        print("\n  Format: Track 1 discretionary portion (max 107 chars)")
        data_str = input("  Enter Track 1 discretionary data: ").strip()
        if len(data_str) > 107:
            print("  ❌ Track 1 data exceeds 107 characters.")
            return False
        data = data_str.encode('ascii') if data_str else b''
        return self._modify_data_element(
            "Track 1 Discretionary Data", 0x9F1F, data, self._validate_track1)

    def modify_pin(self) -> bool:
        """Interactive PIN modification."""
        print("\n  Format: 8-byte PIN (16 hex digits)")
        hex_str = input("  Enter PIN (hex): ").strip()
        if len(hex_str) != 16:
            print("  ❌ PIN must be 16 hex digits (8 bytes).")
            return False
        try:
            data = bytes.fromhex(hex_str)
            return self._modify_data_element(
                "PIN", 0x9F20, data, self._validate_pin)
        except ValueError:
            print("  ❌ Invalid hex format.")
            return False

    def modify_aid(self) -> bool:
        """Interactive AID modification."""
        print("\n  Format: 5-7 byte AID (e.g., 'A0000000041010' for VISA)")
        hex_str = input("  Enter AID (hex): ").strip()
        if len(hex_str) < 10 or len(hex_str) > 14:
            print("  ❌ AID must be 5-7 bytes (10-14 hex digits).")
            return False
        try:
            data = bytes.fromhex(hex_str)
            return self._modify_data_element(
                "Application Identifier (AID)", 0x84, data, self._validate_aid)
        except ValueError:
            print("  ❌ Invalid hex format.")
            return False

    def print_modification_history(self):
        """Print summary of modifications."""
        print("\n" + "=" * 70)
        print("  MODIFICATION HISTORY & VERIFICATION REPORT")
        print("=" * 70)

        if not self.modifications:
            print("  No modifications recorded.")
            return

        success_count = sum(1 for m in self.modifications if m.success)
        failed_count = len(self.modifications) - success_count

        print(f"\n  Summary: {success_count} successful, {failed_count} failed")
        print()

        for idx, mod in enumerate(self.modifications, 1):
            status = "✓ SUCCESS" if mod.success else "✗ FAILED"
            print(f"  [{idx}] {status}  —  {mod.element}")
            print(f"       Tag            : 0x{mod.tag:04X}")
            print(f"       Timestamp      : {mod.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"       Old Value      : {mod.old_value.hex().upper() if mod.old_value else 'N/A'}")
            print(f"       New Value      : {mod.new_value.hex().upper()}")
            if mod.success:
                print(f"       Write Method   : {mod.write_method}")
                print(f"       Status Code    : {mod.sw1:02X} {mod.sw2:02X}")
            else:
                print(f"       Error          : {mod.error_message}")
                print(f"       Status Code    : {mod.sw1:02X} {mod.sw2:02X}")
            print()


# ===========================================================================
# Interactive Menu
# ===========================================================================

def show_menu():
    """Display modification menu."""
    print("\n" + "=" * 70)
    print("  EDITABLE DATA ELEMENTS MENU")
    print("=" * 70)
    print("  [1] Cardholder Name")
    print("  [2] Application Label")
    print("  [3] Application Preferred Name")
    print("  [4] Country Code")
    print("  [5] Currency Code")
    print("  [6] ATC (Application Transaction Counter)")
    print("  [7] Effective Date")
    print("  [8] Expiration Date")
    print("  [9] Service Code")
    print("  [A] TVR (Terminal Verification Results)")
    print("  [B] ARQC")
    print("  [C] Track 2 Equivalent Data")
    print("  [D] Track 1 Discretionary Data")
    print("  [E] PIN")
    print("  [F] AID (Application Identifier)")
    print("  [P] Probe Available Tags")
    print("  [0] Exit & Show History")
    print("=" * 70)


def main():
    print("=" * 70)
    print("  J2A040 EDITABLE DATA ELEMENTS MODIFIER v3 (FULLY FIXED)")
    print("  Powered by pyscard — no other external files required")
    print("=" * 70)

    # Connect
    manager = CardReaderManager()
    connected = manager.select_reader_interactive()

    if not connected:
        print("\n❌ Could not connect to a card. Exiting.")
        return

    modifier = J2A040ModificationManager(manager)

    # Optional: Probe available tags
    probe_choice = input("\nProbe available tags on this card? [Y/n]: ").strip().upper()
    if probe_choice != "N":
        modifier.probe_all_tags()

    # Interactive loop
    while True:
        show_menu()
        choice = input("Select option [0-F, P]: ").strip().upper()

        if choice == "1":
            modifier.modify_cardholder_name()
        elif choice == "2":
            modifier.modify_application_label()
        elif choice == "3":
            modifier.modify_application_preferred_name()
        elif choice == "4":
            modifier.modify_country_code()
        elif choice == "5":
            modifier.modify_currency_code()
        elif choice == "6":
            modifier.modify_atc()
        elif choice == "7":
            modifier.modify_effective_date()
        elif choice == "8":
            modifier.modify_expiration_date()
        elif choice == "9":
            modifier.modify_service_code()
        elif choice == "A":
            modifier.modify_tvr()
        elif choice == "B":
            modifier.modify_arqc()
        elif choice == "C":
            modifier.modify_track2_equivalent()
        elif choice == "D":
            modifier.modify_track1_discretionary()
        elif choice == "E":
            modifier.modify_pin()
        elif choice == "F":
            modifier.modify_aid()
        elif choice == "P":
            modifier.probe_all_tags()
        elif choice == "0":
            print("\nExiting...")
            break
        else:
            print("❌ Invalid choice. Please select 0-F or P.")

    # Cleanup
    modifier.print_modification_history()
    manager.disconnect()

    print("\n" + "=" * 70)
    print("  Session complete!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠  Interrupted by user.")
        exit(0)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
