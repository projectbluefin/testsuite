@extensions_suite @sjc_gold
Feature: SJC Gold desktop card
  The SJC Gold card displays its fixed labels on the desktop and follows its
  position preferences without requiring successful external price requests.

  Background:
    Given Hive extension "sjc-gold" is installed

  Scenario: Enabling SJC Gold renders its card and fixed price labels
    When I enable the selected Hive extension
    Then exactly one SJC Gold desktop card is mapped and allocated
    And the SJC Gold header reads "GIÁ VÀNG SJC"
    And the SJC Gold price labels are rendered:
      | text    |
      | MUA VÀO |
      | BÁN RA  |

  Scenario: Left and top preferences move the rendered card independently
    When I set the SJC Gold "left" preference to 20
    And I set the SJC Gold "top" preference to 30
    And I enable the selected Hive extension
    Then the SJC Gold card is rendered at left 20 and top 30 on the primary monitor
    When I set the SJC Gold "left" preference to 80
    Then the SJC Gold card is rendered at left 80 and top 30 on the primary monitor
    When I set the SJC Gold "top" preference to 60
    Then the SJC Gold card is rendered at left 80 and top 60 on the primary monitor

  Scenario: Disabling removes the card and reenabling creates one rendered card
    When I enable the selected Hive extension
    Then exactly one SJC Gold desktop card is mapped and allocated
    When I disable the selected Hive extension
    Then no SJC Gold desktop card remains in the Shell actor tree
    When I enable the selected Hive extension
    Then exactly one SJC Gold desktop card is mapped and allocated
    And the SJC Gold header reads "GIÁ VÀNG SJC"
    And the SJC Gold price labels are rendered:
      | text    |
      | MUA VÀO |
      | BÁN RA  |

  Scenario: Missing curl_cffi dependency surfaces an actionable error and cleans up on disable
    Given the SJC Gold Python helper is replaced with a missing curl_cffi stub
    When I enable the selected Hive extension
    Then exactly one SJC Gold desktop card is mapped and allocated
    And the SJC Gold card renders the actionable missing-curl_cffi error text
    And no SJC Gold helper or python child process remains for the candidate
    When I disable the selected Hive extension
    Then no SJC Gold desktop card remains in the Shell actor tree
    And no SJC Gold helper or python child process remains for the candidate
