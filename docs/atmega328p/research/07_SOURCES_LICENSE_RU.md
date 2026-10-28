# Источники, provenance и лицензия

## Оригинальный Optiboot

- Официальный GitHub: https://github.com/Optiboot/optiboot
- Исходный C-код: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/optiboot.c
- Исходный список команд: https://github.com/Optiboot/optiboot/blob/master/optiboot/bootloaders/optiboot/stk500.h
- Контрольное значение GitHub blob для изученного в этом разговоре `optiboot.c`: `d7fba90a02616f095ec733ac4c434b4d42db58a6`. Это Git blob SHA из того чтения, **не закреплённая версия всего репозитория**.
- Оригинальный бинарник `optiboot_atmega328.hex` (заявленная версия 8.3): приложен в `OFFICIAL_REFERENCE/` и в промежуточных проектах для сравнения. Его коды и функциональные опции могут отличаться от текущего HEAD C-исходника.
- **Полное оригинальное дерево исходников GitHub в этот архив не входит**, потому что оно не было локально сохранено при исследовании. Его можно получить внешним `git clone https://github.com/Optiboot/optiboot.git` или `HISTORY_SOURCES/01_initial_size_lab/download_upstream.sh`. Это надо учитывать при сравнении с оригиналом и не заявлять, что официальный источник «уже полностью скачан».

## Протокол и MCU

- AVR061 STK500v1: https://ww1.microchip.com/downloads/en/AppNotes/doc2525.pdf
- ATmega328P datasheet, Atmel 7810D: https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf
- ATmega328/P datasheet Atmel-42735B (в т. ч. уточнённые `EEAR9:8`): https://docs.arduino.cc/resources/datasheets/Atmel-42735-8-bit-AVR-Microcontroller-ATmega328-328P_Datasheet.pdf
- Microchip DS40002061B: https://www.microchip.com/content/dam/mchp/documents/MCU08/ProductDocuments/DataSheets/ATmega48A-PA-88A-PA-168A-PA-328-P-DS-DS40002061B.pdf
- avrdude `stk500.c`: https://github.com/avrdudes/avrdude/blob/main/src/stk500.c
- Optiboot EEPROM адресация в avrdude: https://github.com/Optiboot/optiboot/issues/235

## Лицензия

Производный код Optiboot в данном проекте распространяется с лицензией **GPL-2.0-or-later**, как заявлено в исходниках проекта и в `COPYING` из предыдущих архивов. При изменении и распространении производных версий сохранять атрибуцию и условия GPL, сопроводить исходники; избегать необоснованных заявлений о согласовании с разработчиками оригинала.

## Границы подтверждения

Первоисточники рассматривались при исследовании. Эмуляционные тесты, исходники и бинарники включены; **электрические/аппаратные измерения, осциллограммы, записи реального avrdude не создавались**.
