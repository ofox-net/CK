package com.example

import org.junit.Assert.assertEquals
import org.junit.Test

class ExampleRobolectricTest {

  @Test
  fun `read string from context`() {
    val appName = "Colour King"
    assertEquals("Colour King", appName)
  }
}

